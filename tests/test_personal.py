"""Personal grants, protected state, context isolation and exact HTTP requests."""

import asyncio
import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from dinero_cli.auth import AuthService
from dinero_cli.cli import app
from dinero_cli.client import APIClient
from dinero_cli.commands import auth as commands
from dinero_cli.config import Settings, load_settings, save_setting
from dinero_cli.errors import CLIError
from dinero_cli.personal import TOKEN, parse_credentials
from dinero_cli.secrets import SecretStore

VALUES = {
    "client_id": "personal-client",
    "client_secret": "sentinel-personal-secret",
    "api_key": "sentinel-api-key",
    "organization": "123",
}
RESPONSE = {
    "access_token": "sentinel-personal-token",
    "expires_in": 3600,
    "token_type": "Bearer",
    "refresh_token": None,
}


@pytest.fixture
def personal(tmp_path):
    settings = Settings(organization="123", credential_backend="file")
    store = SecretStore(settings, tmp_path / "state")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=RESPONSE)

    return AuthService(
        settings, store=store, transport=httpx.MockTransport(respond), now=lambda: 1000
    ), requests


def test_grant_exact_wire_and_renewal(personal):
    service, requests = personal
    with service.store.transaction() as txn:
        txn.state.client_secret = SecretStr("existing-visma-secret")
        txn.save()
    result = service.login_personal(parse_credentials(VALUES))
    assert result["method"] == "personal" and result["organization"] == "123"
    assert result["access_token_valid"] and result["refresh_available"]
    assert "sentinel" not in str(result)
    request = requests[0]
    assert str(request.url) == TOKEN
    assert (
        request.headers["Authorization"]
        == "Basic " + base64.b64encode(b"personal-client:sentinel-personal-secret").decode()
    )
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["password"],
        "scope": ["read write"],
        "username": ["sentinel-api-key"],
        "password": ["sentinel-api-key"],
    }
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert service.credentials().access_token == RESPONSE["access_token"] and len(requests) == 1
    service.now = lambda: 4600
    assert service.credentials().organization == "123" and len(requests) == 2
    with service.store.transaction() as txn:
        assert txn.state.tokens["expires_at"] == 8200
        assert txn.state.tokens["refresh_token"] is None
        assert txn.state.personal.api_key.get_secret_value() == VALUES["api_key"]
    service.logout()
    with service.store.transaction() as txn:
        assert txn.state.personal is None and txn.state.tokens is None
        assert txn.state.client_secret.get_secret_value() == "existing-visma-secret"


@pytest.mark.parametrize(
    "field,value", [("organization", "456"), ("api_base_url", "https://other.example:443")]
)
def test_context_change_fails_without_exchange(personal, field, value):
    service, requests = personal
    service.login_personal(parse_credentials(VALUES))
    setattr(service.settings, field, value)
    if field == "api_base_url":
        service.settings.trusted_api_origins.append(value)
    assert not service.status()["configuration_matches"]
    with pytest.raises(CLIError) as failure:
        service.credentials()
    assert failure.value.code == 3 and len(requests) == 1


def test_wrong_login_org_preserves_existing_state(personal):
    service, requests = personal
    with pytest.raises(CLIError, match="selected organization"):
        service.login_personal(parse_credentials({**VALUES, "organization": "456"}))
    assert not requests and not service.status()["authorized"]


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key": ""},
        {"client_secret": "a\nb"},
        {"client_id": "a:b"},
        {"organization": "org"},
        {"organization": ""},
        {"extra": "sentinel"},
    ],
)
def test_bad_credentials_are_sanitized(changes):
    with pytest.raises(CLIError) as failure:
        parse_credentials({**VALUES, **changes})
    assert failure.value.code == 2 and "sentinel" not in str(failure.value)


@pytest.mark.parametrize(
    "reply,code,status",
    [
        (httpx.Response(401, text="sentinel-api-key"), 3, 401),
        (httpx.Response(429, headers={"Retry-After": "17"}, text="sentinel"), 6, 429),
        (httpx.Response(302, headers={"Location": "https://evil.invalid"}), 3, 302),
        (httpx.Response(201, text="sentinel"), 3, 201),
        (httpx.Response(200, json={**RESPONSE, "token_type": "Basic"}), 3, 200),
        (httpx.Response(200, json={**RESPONSE, "access_token": "bad\ntoken"}), 3, 200),
        (httpx.ReadTimeout("sentinel-api-key"), 5, None),
    ],
)
def test_grant_failures_preserve_previous_authorization(personal, reply, code, status):
    service, requests = personal
    service.login_personal(parse_credentials(VALUES))
    calls = []

    def respond(request):
        calls.append(request)
        if isinstance(reply, Exception):
            raise reply
        return reply

    service.transport = httpx.MockTransport(respond)
    with pytest.raises(CLIError) as failure:
        service.login_personal(parse_credentials(VALUES))
    assert failure.value.code == code and failure.value.status == status and len(calls) == 1
    assert "sentinel" not in str(failure.value.payload())
    if status == 429:
        assert failure.value.details == {"retry_after": "17"}
    assert service.status()["authorized"]


@pytest.mark.parametrize(
    "path,allowed",
    [
        ("/v1/123/contacts", True),
        ("/v1.2/123/invoices", True),
        ("/v1/456/contacts", False),
        ("/v1/%34%35%36/contacts", False),
        ("/unexpected", False),
        ("/v1/organizations", True),
    ],
)
def test_actual_api_path_cannot_override_organization(personal, path, allowed):
    service, _ = personal
    service.login_personal(parse_credentials(VALUES))
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    client = APIClient(service.settings, auth=service, transport=httpx.MockTransport(respond))
    if allowed:
        assert asyncio.run(client.request("GET", path)) == {"ok": True}
        assert len(sent) == 1
    else:
        with pytest.raises(CLIError) as failure:
            asyncio.run(client.request("GET", path))
        assert failure.value.code == 3 and not sent


def test_personal_secret_response_redaction(personal):
    service, _ = personal
    service.login_personal(parse_credentials(VALUES))
    client = APIClient(
        service.settings,
        auth=service,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"Message": "Rejected " + VALUES["api_key"]})
        ),
    )
    with pytest.raises(CLIError) as failure:
        asyncio.run(client.request("POST", "/v1/123/contacts"))
    assert "sentinel" not in str(failure.value.payload())


@pytest.mark.parametrize("stdin", [True, False])
def test_login_command_file_and_stdin(tmp_path, monkeypatch, stdin):
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(tmp_path / "state"))
    save_setting("credential-backend", "file")
    monkeypatch.setattr(
        commands,
        "AuthService",
        lambda settings: AuthService(
            settings,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=RESPONSE)),
        ),
    )
    path = tmp_path / "personal.json"
    path.write_text(json.dumps(VALUES))
    path.chmod(0o600)
    result = CliRunner().invoke(
        app,
        [
            "auth",
            "login-personal",
            "--organization",
            "123",
            "--input",
            "-" if stdin else str(path),
            "--json",
        ],
        input=json.dumps(VALUES) if stdin else None,
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["method"] == "personal"
    assert "sentinel" not in result.stdout + result.stderr
    with SecretStore(load_settings()).transaction() as txn:
        assert txn.state.personal.api_key.get_secret_value() == VALUES["api_key"]


def test_concurrent_personal_renewal_is_serialized(personal):
    from concurrent.futures import ThreadPoolExecutor

    service, requests = personal
    service.login_personal(parse_credentials(VALUES))
    service.now = lambda: 4600
    with ThreadPoolExecutor(max_workers=4) as workers:
        tokens = list(workers.map(lambda _: service.access_token(), range(4)))
    assert tokens == [RESPONSE["access_token"]] * 4
    assert len(requests) == 2  # Initial login and exactly one renewal.


def test_successful_visma_login_removes_personal_credentials(personal):
    service, _ = personal
    service.login_personal(parse_credentials(VALUES))
    service.settings.client_id = "visma-client"
    with service.store.transaction() as txn:
        txn.state.client_secret = SecretStr("visma-secret")
        txn.save()
    service.login(lambda *args: "code")
    with service.store.transaction() as txn:
        assert txn.state.personal is None and txn.state.tokens["method"] == "visma"
    assert service.status()["configuration_matches"]


def test_personal_missing_saved_key_cannot_fall_back_to_visma(personal):
    service, requests = personal
    service.login_personal(parse_credentials(VALUES))
    with service.store.transaction() as txn:
        txn.state.personal = None
        txn.save()
    with pytest.raises(CLIError) as failure:
        service.access_token()
    assert failure.value.code == 3 and len(requests) == 1
