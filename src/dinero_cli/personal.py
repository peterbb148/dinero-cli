"""Dinero personal-integration credentials and its organization-specific token grant."""

import base64
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from dinero_cli.errors import CLIError
from dinero_cli.redaction import redact

TOKEN = "https://authz.dinero.dk/dineroapi/oauth/token"


class PersonalGrant(BaseModel):
    """Validate access-token fields; personal grants never use OAuth refresh tokens."""

    access_token: SecretStr = Field(repr=False, min_length=1)
    expires_in: float = Field(gt=0, allow_inf_nan=False)
    token_type: str


class PersonalCredentials(BaseModel):
    """Private credentials supplied by Dinero for a single organization's API key."""

    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1)
    client_secret: SecretStr = Field(repr=False, min_length=1)
    api_key: SecretStr = Field(repr=False, min_length=1)
    organization: str

    @field_validator("client_id", "organization")
    @classmethod
    def public_fields(cls, value: str, info: Any) -> str:
        """Reject ambiguous Basic identities and require the explicit numeric organization."""
        if (
            not value.isascii()
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or ":" in value
        ):
            raise ValueError("Invalid personal credential context")
        if info.field_name == "organization" and not value.isdigit():
            raise ValueError("Invalid organization")
        return value

    @field_validator("client_secret", "api_key")
    @classmethod
    def secret_fields(cls, value: SecretStr) -> SecretStr:
        """Require nonempty credential values without control or whitespace characters."""
        raw = value.get_secret_value()
        if not raw.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw):
            raise ValueError("Invalid credential")
        return value

    def storage(self) -> dict[str, Any]:
        """Serialize secrets only for the protected-store boundary."""
        return {
            **self.model_dump(),
            "client_secret": self.client_secret.get_secret_value(),
            "api_key": self.api_key.get_secret_value(),
        }

    def redactions(self) -> tuple[str, ...]:
        """Include the Basic header encoding as well as each secret in redaction material."""
        secret = self.client_secret.get_secret_value()
        encoded = base64.b64encode(f"{self.client_id}:{secret}".encode()).decode()
        return secret, self.api_key.get_secret_value(), encoded


def parse_credentials(value: Any) -> PersonalCredentials:
    """Never expose validation inputs in a credential diagnostic."""
    try:
        return PersonalCredentials.model_validate(value)
    except ValidationError as error:
        raise CLIError(
            "Personal credentials require client_id, client_secret, api_key and organization."
        ) from error


def exchange(
    credentials: PersonalCredentials, transport: httpx.BaseTransport | None
) -> tuple[bytes, int]:
    """Exchange one API key grant with fixed TLS origin, without redirects or retries."""
    key = credentials.api_key.get_secret_value()
    try:
        with httpx.Client(
            transport=transport, timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = client.post(
                TOKEN,
                auth=httpx.BasicAuth(
                    credentials.client_id, credentials.client_secret.get_secret_value()
                ),
                data={
                    "grant_type": "password",
                    "scope": "read write",
                    "username": key,
                    "password": key,
                },
            )
    except httpx.HTTPError as error:
        raise CLIError(
            "Personal token exchange failed; no automatic retry was made.", code=5
        ) from error
    if not response.is_success:
        raise CLIError(
            "Dinero rejected the personal token grant.",
            code=6 if response.status_code == 429 else 3,
            status=response.status_code,
            details={
                "retry_after": redact(response.headers["retry-after"], credentials.redactions())
            }
            if response.status_code == 429 and "retry-after" in response.headers
            else {},
        )
    return response.content, response.status_code
