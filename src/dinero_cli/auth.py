"""Visma authorization and serialized token rotation; never expose grant responses."""

import base64
import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from dinero_cli.config import Settings, require_trusted_origin
from dinero_cli.errors import CLIError
from dinero_cli.personal import PersonalCredentials
from dinero_cli.personal import exchange as personal_exchange
from dinero_cli.secrets import SecretStore, Transaction

AUTHORIZE = "https://connect.visma.com/connect/authorize"
TOKEN = "https://connect.visma.com/connect/token"


@dataclass(frozen=True)
class Credentials:
    """Internal bearer material and values that must be removed from remote diagnostics."""

    access_token: str = field(repr=False)
    redactions: tuple[str, ...] = field(repr=False)
    organization: str | None = None


def credentials(
    record: "TokenRecord", secret: SecretStr | None, *previous: SecretStr | None
) -> Credentials:
    """Keep credential values together without exposing them in object representations."""
    values = (record.access_token, record.refresh_token, secret, *previous)
    return Credentials(
        record.access_token.get_secret_value(),
        tuple(value.get_secret_value() for value in values if value is not None),
    )


class TokenRecord(BaseModel):
    """Private persisted tokens bound to the authorizing client and API origin."""

    model_config = ConfigDict(extra="forbid")
    access_token: SecretStr = Field(repr=False, min_length=1)
    refresh_token: SecretStr | None = Field(default=None, repr=False, min_length=1)
    expires_at: float = Field(allow_inf_nan=False, gt=0)
    client_id: str
    api_origin: str
    method: Literal["visma", "personal"] = "visma"
    organization: str | None = None

    def storage(self) -> dict[str, Any]:
        """Return plaintext only for the protected store's serialization boundary."""
        values = self.model_dump()
        values["access_token"] = self.access_token.get_secret_value()
        values["refresh_token"] = (
            self.refresh_token.get_secret_value() if self.refresh_token is not None else None
        )
        return values


class Grant(BaseModel):
    """Validate the needed fields and discard id_tokens and other unused response data."""

    access_token: SecretStr = Field(repr=False, min_length=1)
    refresh_token: SecretStr | None = Field(default=None, repr=False, min_length=1)
    expires_in: float = Field(gt=0, allow_inf_nan=False)
    token_type: str


def read_record(values: dict[str, Any] | None) -> TokenRecord | None:
    """Turn malformed protected state into a sanitized authentication failure."""
    if values is None:
        return None
    try:
        return TokenRecord.model_validate(values)
    except ValidationError as error:
        raise CLIError("Stored authorization is invalid; run auth login again.", code=3) from error


class AuthService:
    """Own OAuth exchange and refresh, independent of terminal and organization context."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: SecretStore | None = None,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.store = store
        self.transport = transport
        self.now = now

    def secret_store(self) -> SecretStore:
        """Require the explicitly configured protected backend only when it is needed."""
        return self.store if self.store is not None else SecretStore(self.settings)

    def client_id(self) -> str:
        """Require a registered client, never a bundled shared client secret."""
        if self.settings.client_id is None:
            raise CLIError("Set client-id for your registered Visma web application.")
        return self.settings.client_id

    def matches(self, record: TokenRecord, personal: PersonalCredentials | None = None) -> bool:
        """Prevent forwarding authorization to a different client or API origin."""
        if record.method == "personal":
            return bool(
                personal is not None
                and record.client_id == personal.client_id
                and record.organization == personal.organization
                and self.settings.organization == personal.organization
                and record.api_origin == self.settings.api_base_url
            )
        return (
            record.client_id == self.settings.client_id
            and record.api_origin == self.settings.api_base_url
        )

    def status(self) -> dict[str, Any]:
        """Inspect local authorization without network access or token refresh."""
        record = None
        pending = False
        personal = None
        if self.settings.credential_backend is not None or self.store is not None:
            with self.secret_store().transaction() as transaction:
                record = read_record(transaction.state.tokens)
                pending = transaction.state.refresh_pending
                personal = transaction.state.personal
        matches = record is not None and self.matches(record, personal)
        result: dict[str, Any] = {
            "authorized": record is not None,
            "access_token_valid": bool(
                record is not None and matches and not pending and record.expires_at > self.now()
            ),
            "refresh_available": bool(
                record is not None
                and (
                    record.refresh_token is not None
                    or (record.method == "personal" and personal is not None)
                )
            ),
            "expires_at": record.expires_at if record is not None else None,
            "configuration_matches": matches,
            "refresh_pending": pending,
        }

        if record is not None and record.method == "personal":
            result.update(method="personal", organization=record.organization)
        return result

    def logout(self) -> dict[str, bool]:
        """Delete local token state only, preserving the configured application secret."""
        with self.secret_store().transaction() as transaction:
            transaction.state.tokens = None
            transaction.state.personal = None
            transaction.state.refresh_pending = False
            transaction.save()
        return {"logged_out": True}

    def exchange(self, fields: dict[str, str]) -> Grant:
        """Post one URL-encoded grant with TLS, fixed origin, no redirects or retries."""
        try:
            with httpx.Client(
                transport=self.transport, timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = client.post(TOKEN, data=fields)
        except httpx.HTTPError as error:
            raise CLIError(
                "Visma token exchange failed; authorize again before retrying.", code=5
            ) from error
        if not response.is_success:
            raise CLIError(
                "Visma rejected the token grant; check registration or authorize again.",
                code=3,
                status=response.status_code,
            )
        try:
            grant = Grant.model_validate_json(response.content)
            value = grant.access_token.get_secret_value()
            if (
                grant.token_type.lower() != "bearer"
                or not value.isascii()
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError("Unsupported bearer token")
            return grant
        except (ValidationError, ValueError) as error:
            raise CLIError(
                "Visma returned an invalid token response.", code=3, status=response.status_code
            ) from error

    def record(self, grant: Grant, *, previous_refresh: SecretStr | None = None) -> TokenRecord:
        """Associate the returned access token with the explicit authorization context."""
        return TokenRecord(
            access_token=grant.access_token,
            refresh_token=grant.refresh_token or previous_refresh,
            expires_at=self.now() + grant.expires_in,
            client_id=self.client_id(),
            api_origin=self.settings.api_base_url,
        )

    def access_token(self) -> str:
        """Return only the bearer value to internal callers that do not render API errors."""
        return self.credentials().access_token

    def credentials(self) -> Credentials:
        """Return valid bearer material, rotating under one process lock when needed.

        Persist a pending marker before sending a refresh grant. If the process dies or
        exchange/save fails, a later process cannot replay a potentially consumed token.
        Async callers must run this complete blocking transaction in a worker thread.
        """
        require_trusted_origin(self.settings)
        with self.secret_store().transaction() as transaction:
            record = read_record(transaction.state.tokens)
            if record is not None and record.method == "personal":
                return self.personal_credentials(transaction, record)
            client_id = self.client_id()
            if record is None or not self.matches(record):
                raise CLIError(
                    "Authorization is missing or its context changed; run auth login.", code=3
                )
            if transaction.state.refresh_pending:
                raise CLIError(
                    "Previous token refresh did not complete; run auth login again.", code=3
                )
            if record.expires_at > self.now() + 30:
                return credentials(record, transaction.state.client_secret)
            secret = transaction.state.client_secret
            if record.refresh_token is None or secret is None:
                raise CLIError("Authorization cannot be refreshed; run auth login again.", code=3)
            transaction.state.refresh_pending = True
            transaction.save()
            grant = self.exchange(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": secret.get_secret_value(),
                    "refresh_token": record.refresh_token.get_secret_value(),
                }
            )
            updated = self.record(grant, previous_refresh=record.refresh_token)
            transaction.state.tokens = updated.storage()
            transaction.state.refresh_pending = False
            transaction.save()
            return credentials(updated, secret, record.access_token, record.refresh_token)

    def login(self, callback: Callable[[str, str], str]) -> dict[str, Any]:
        """Request browser consent, validate callback state in the collector, then save tokens."""
        require_trusted_origin(self.settings)
        client_id = self.client_id()
        store = self.secret_store()
        with store.transaction() as transaction:
            if transaction.state.client_secret is None:
                raise CLIError("Store the Visma client secret with config set-client-secret first.")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        params = {
            "client_id": client_id,
            "response_type": "code",
            "response_mode": self.settings.response_mode,
            "redirect_uri": self.settings.redirect_uri,
            "scope": self.settings.scopes,
            "state": state,
        }
        if self.settings.pkce:
            params["code_challenge_method"] = "S256"
            params["code_challenge"] = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
        code = callback(AUTHORIZE + "?" + urlencode(params), state)
        with store.transaction() as transaction:
            secret = transaction.state.client_secret
            if secret is None:
                raise CLIError("The configured client secret was removed during login.", code=3)
            fields = {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": secret.get_secret_value(),
                "redirect_uri": self.settings.redirect_uri,
                "code": code,
            }
            if self.settings.pkce:
                fields["code_verifier"] = verifier
            grant = self.exchange(fields)
            transaction.state.tokens = self.record(grant).storage()
            transaction.state.personal = None
            transaction.state.refresh_pending = False
            transaction.save()
        return self.status()

    def personal_record(self, personal: PersonalCredentials) -> TokenRecord:
        """Validate a personal grant without accepting OAuth refresh credentials."""
        raw, status = personal_exchange(personal, self.transport)
        try:
            grant = Grant.model_validate_json(raw)
            token = grant.access_token.get_secret_value()
            if (
                grant.token_type.lower() != "bearer"
                or not token.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)
            ):
                raise ValueError("Invalid bearer token")
        except (ValidationError, ValueError) as error:
            raise CLIError(
                "Dinero returned an invalid personal token response.", code=3, status=status
            ) from error
        return TokenRecord(
            access_token=grant.access_token,
            expires_at=self.now() + grant.expires_in,
            client_id=personal.client_id,
            api_origin=self.settings.api_base_url,
            method="personal",
            organization=personal.organization,
        )

    def login_personal(self, personal: PersonalCredentials) -> dict[str, Any]:
        """Replace authorization using an explicit organization-specific personal grant."""
        require_trusted_origin(self.settings)
        if self.settings.organization != personal.organization:
            raise CLIError("Personal credentials must match the selected organization.")
        with self.secret_store().transaction() as transaction:
            record = self.personal_record(personal)
            transaction.state.personal = personal
            transaction.state.tokens = record.storage()
            transaction.state.refresh_pending = False
            transaction.save()
        return self.status()

    def personal_credentials(self, transaction: Transaction, record: TokenRecord) -> Credentials:
        """Renew an expiring personal grant under the existing cross-process lock."""
        personal = transaction.state.personal
        if personal is None or not self.matches(record, personal):
            raise CLIError(
                "Personal authorization does not match the selected organization or API origin.",
                code=3,
            )
        previous = record.access_token.get_secret_value()
        if record.expires_at <= self.now() + 30:
            record = self.personal_record(personal)
            transaction.state.tokens = record.storage()
            transaction.save()
        return Credentials(
            record.access_token.get_secret_value(),
            (previous, record.access_token.get_secret_value(), *personal.redactions()),
            organization=personal.organization,
        )
