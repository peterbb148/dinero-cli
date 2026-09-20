"""Offline command contracts for actual auth callbacks and services."""

import json
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import httpx
from config_cases import IO, PARSER, error, failed_read, fresh, invalid
from pydantic import SecretStr
from pytest import MonkeyPatch

from devtools.contracts import Case, Contract
from dinero_cli.auth import AuthService
from dinero_cli.commands import auth as commands
from dinero_cli.config import load_settings, save_setting
from dinero_cli.secrets import SecretStore

EMPTY = {
    "authorized": False,
    "access_token_valid": False,
    "refresh_available": False,
    "expires_at": None,
    "configuration_matches": False,
    "refresh_pending": False,
}
LOGGED_IN = {
    "authorized": True,
    "access_token_valid": True,
    "refresh_available": True,
    "expires_at": 4600.0,
    "configuration_matches": True,
    "refresh_pending": False,
}
INVALID = "Invalid configuration. Use config --help for supported settings."
DENIED = "Visma rejected the token grant; check registration or authorize again."


@contextmanager
def configured(status=200, transport_error=False, malformed=False):
    with fresh(), MonkeyPatch.context() as patch:
        save_setting("client-id", "registered-app")
        save_setting("credential-backend", "file")
        store = SecretStore(load_settings())
        with store.transaction() as txn:
            txn.state.client_secret = SecretStr("contract-client-secret")
            if malformed:
                txn.state.tokens = {"access_token": "contract-access-token"}
            txn.save()

        def exchange(request):
            if transport_error:
                raise httpx.ReadTimeout("contract-client-secret")
            return httpx.Response(
                status,
                json={
                    "access_token": "contract-access-token",
                    "refresh_token": "contract-refresh-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )

        patch.setattr(
            commands,
            "AuthService",
            lambda settings: AuthService(
                settings, transport=httpx.MockTransport(exchange), now=lambda: 1000
            ),
        )
        patch.setattr(commands, "collect", lambda *args, **kwargs: "contract-code")
        yield


@contextmanager
def rejected():
    with configured(status=400):
        yield


@contextmanager
def transport_failure():
    with configured(transport_error=True):
        yield


@contextmanager
def malformed_record():
    with configured(malformed=True):
        yield


NO_API = {"api": "OAuth/local commands do not issue Dinero accounting API requests."}
CONTRACTS = {
    ("auth",): Contract(
        kind="group", options=frozenset(), reason="User-based Visma authorization namespace."
    ),
    ("auth", "login"): Contract(
        kind="data",
        options=frozenset(
            {"--json", "--no-browser", "--authorization-url-file", "--callback-file", "--timeout"}
        ),
        reason="Explicit authorization mutation reports only safe status metadata.",
        excluded_failures=NO_API,
        cases=(
            Case((), expected=LOGGED_IN, human=("authorized", "Yes"), setup=configured),
            Case(
                ("--timeout", "0"),
                expected=error(PARSER),
                human=(PARSER,),
                exit_code=2,
                failure="validation",
                setup=fresh,
            ),
            Case(
                (),
                expected={**error(DENIED), "status": 400},
                human=(DENIED,),
                exit_code=3,
                failure="authentication",
                setup=rejected,
            ),
            Case(
                (),
                expected=error("Visma token exchange failed; authorize again before retrying."),
                human=("Visma token exchange failed",),
                exit_code=5,
                failure="transport",
                setup=transport_failure,
            ),
        ),
    ),
    ("auth", "status"): Contract(
        kind="data",
        options=frozenset({"--json"}),
        reason="Read-only non-secret authorization status.",
        excluded_failures=NO_API,
        cases=(
            Case((), expected=EMPTY, human=("authorized", "No"), setup=fresh),
            Case(
                (),
                expected=error(INVALID),
                human=(INVALID,),
                exit_code=2,
                failure="validation",
                setup=invalid,
            ),
            Case(
                (),
                expected=error("Stored authorization is invalid; run auth login again."),
                human=("Stored authorization is invalid",),
                exit_code=3,
                failure="authentication",
                setup=malformed_record,
            ),
            Case(
                (),
                expected=error(IO),
                human=(IO,),
                exit_code=5,
                failure="transport",
                setup=failed_read,
            ),
        ),
    ),
    ("auth", "logout"): Contract(
        kind="data",
        options=frozenset({"--json"}),
        reason="Explicit local token removal reports completion; it is not server revocation.",
        excluded_failures={
            **NO_API,
            "authentication": "Local token removal does not require valid authorization.",
        },
        cases=(
            Case((), expected={"logged_out": True}, human=("logged_out", "Yes"), setup=configured),
            Case(
                (),
                expected=error(INVALID),
                human=(INVALID,),
                exit_code=2,
                failure="validation",
                setup=invalid,
            ),
            Case(
                (),
                expected=error(IO),
                human=(IO,),
                exit_code=5,
                failure="transport",
                setup=failed_read,
            ),
        ),
    ),
}


@contextmanager
def personal_configured(status=200, transport_error=False):
    with configured(status=status, transport_error=transport_error):
        save_setting("organization", "123")
        path = Path("personal.json")
        path.write_text(
            json.dumps(
                {
                    "client_id": "personal-client",
                    "client_secret": "contract-client-secret",
                    "api_key": "contract-api-key",
                    "organization": "123",
                }
            )
        )
        path.chmod(0o600)
        yield


CONTRACTS[("auth", "login-personal")] = Contract(
    kind="data",
    options=frozenset({"--input", "--organization", "--json"}),
    reason="Explicit personal organization authorization, with credentials only in private input.",
    excluded_failures=NO_API,
    cases=(
        Case(
            ("--input", "personal.json"),
            expected={**LOGGED_IN, "method": "personal", "organization": "123"},
            human=("personal", "123", "Yes"),
            setup=personal_configured,
        ),
        Case(
            ("--input", "personal.json", "--organization", "456"),
            expected=error("Personal credentials must match the selected organization."),
            human=("selected organization",),
            exit_code=2,
            failure="validation",
            setup=personal_configured,
        ),
        Case(
            ("--input", "personal.json"),
            expected={**error("Dinero rejected the personal token grant."), "status": 401},
            human=("HTTP 401", "rejected"),
            exit_code=3,
            failure="authentication",
            setup=partial(personal_configured, status=401),
        ),
        Case(
            ("--input", "personal.json"),
            expected=error("Personal token exchange failed; no automatic retry was made."),
            human=("Personal token exchange failed",),
            exit_code=5,
            failure="transport",
            setup=partial(personal_configured, transport_error=True),
        ),
    ),
)
