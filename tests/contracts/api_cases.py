"""Real API command contracts with only the HTTP transport replaced."""

from contextlib import contextmanager
from functools import partial

import httpx
from config_cases import error, fresh
from pydantic import SecretStr
from pytest import MonkeyPatch

from devtools.contracts import Case, Contract
from dinero_cli.auth import TokenRecord
from dinero_cli.client import APIClient
from dinero_cli.commands import api as commands
from dinero_cli.config import load_settings, save_setting
from dinero_cli.secrets import SecretStore


@contextmanager
def configured(value=None, status=200, transport_error=False, authorized=True):
    with fresh(), MonkeyPatch.context() as patch:
        save_setting("client-id", "contract-client")
        save_setting("credential-backend", "file")
        save_setting("organization", "123")
        settings = load_settings()
        with SecretStore(settings).transaction() as txn:
            txn.state.client_secret = SecretStr("contract-client-secret")
            if authorized:
                txn.state.tokens = TokenRecord(
                    access_token=SecretStr("contract-access-token"),
                    expires_at=4_000_000_000,
                    client_id=settings.client_id,
                    api_origin=settings.api_base_url,
                ).storage()
            txn.save()

        def respond(request):
            if transport_error:
                raise httpx.ReadTimeout("contract-access-token")
            if value is None:
                return httpx.Response(status)
            return httpx.Response(status, json=value)

        patch.setattr(
            commands,
            "APIClient",
            lambda settings: APIClient(settings, transport=httpx.MockTransport(respond)),
        )
        yield


def command_contract(method):
    path = ("/v1/{organizationId}/contacts",)
    options = {"--json", "--query", "--organization"}
    if method != "get":
        options.add("--input")
    transport = "API transport failed."
    if method != "get":
        transport += " The write result is uncertain; inspect server state before repeating it."
    missing = "Authorization is missing or its context changed; run auth login."
    return Contract(
        kind="data",
        options=frozenset(options),
        reason=f"One explicit HTTP {method.upper()} request, preserving the API response.",
        cases=(
            Case(path, expected=None, human=("Completed",), setup=configured),
            Case(path, expected=[], human=("No results",), setup=partial(configured, value=[])),
            Case(
                path,
                expected={"Name": "Æble"},
                human=("Name", "Æble"),
                setup=partial(configured, value={"Name": "Æble"}),
            ),
            Case(
                path,
                expected=[{"Name": "Æble"}],
                human=("Name", "Æble"),
                setup=partial(configured, value=[{"Name": "Æble"}]),
            ),
            Case(
                (*path, "--query", "invalid"),
                expected=error("Each --query must be KEY=VALUE with a nonempty key."),
                human=("Each --query",),
                exit_code=2,
                failure="validation",
                setup=configured,
            ),
            Case(
                path,
                expected=error(missing),
                human=(missing,),
                exit_code=3,
                failure="authentication",
                setup=partial(configured, authorized=False),
            ),
            Case(
                path,
                expected={
                    "error": True,
                    "status": 400,
                    "message": "Rejected",
                    "details": {"response": {"Message": "Rejected"}},
                },
                human=("HTTP 400", "Rejected"),
                exit_code=4,
                failure="api",
                setup=partial(configured, status=400, value={"Message": "Rejected"}),
            ),
            Case(
                path,
                expected=error(transport),
                human=("API transport failed",),
                exit_code=5,
                failure="transport",
                setup=partial(configured, transport_error=True),
            ),
        ),
    )


CONTRACTS = {
    ("api",): Contract(kind="group", options=frozenset(), reason="Raw JSON API namespace."),
    **{("api", method): command_contract(method) for method in ("get", "post", "put", "delete")},
}
