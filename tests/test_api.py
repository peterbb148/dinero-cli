"""Exercise real CLI parsing, credentials, HTTP construction and output together."""

import json
import time
from urllib.parse import parse_qsl

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from dinero_cli.auth import TokenRecord
from dinero_cli.cli import app
from dinero_cli.client import APIClient
from dinero_cli.commands import api
from dinero_cli.config import Settings, load_settings, save_setting
from dinero_cli.secrets import SecretStore


@pytest.fixture
def wire(tmp_path, monkeypatch):
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(tmp_path / "state"))
    for name in Settings.model_fields:
        monkeypatch.delenv("DINERO_" + name.upper(), raising=False)
    save_setting("client-id", "test-client")
    save_setting("credential-backend", "file")
    save_setting("organization", "123")
    settings = load_settings()
    with SecretStore(settings).transaction() as txn:
        txn.state.client_secret = SecretStr("sentinel-client-secret")
        txn.state.tokens = TokenRecord(
            access_token=SecretStr("sentinel-access-token"),
            refresh_token=SecretStr("sentinel-refresh-token"),
            expires_at=time.time() + 3600,
            client_id=settings.client_id,
            api_origin=settings.api_base_url,
        ).storage()
        txn.save()
    requests = []
    responses = [httpx.Response(200, json={"Name": "Æble", "ContactGuid": "guid"})]

    def handle(request):
        requests.append(request)
        result = responses[0]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        api,
        "APIClient",
        lambda settings: APIClient(settings, transport=httpx.MockTransport(handle)),
    )
    return CliRunner(), requests, responses


@pytest.mark.parametrize("method", ["get", "post", "put", "delete"])
@pytest.mark.parametrize("stdin", [False, True])
def test_cli_wire_method_path_queries_body_and_output(wire, tmp_path, method, stdin):
    runner, requests, _ = wire
    payload = {"ContactGuid": "original", "Lines": [{"Description": "Ø & =", "Amount": 12.5}]}
    arguments = ["api", method, "/v1/{organizationId}/contacts", "--organization", "456"]
    pairs = [
        ("fields", "Name"),
        ("queryFilter", "Name eq 'A&B+=æ'"),
        ("fields", "Email"),
        ("x", ""),
    ]
    for key, value in pairs:
        arguments += ["--query", f"{key}={value}"]
    source = None
    if method != "get":
        source = json.dumps(payload, ensure_ascii=False)
        file = tmp_path / "body.json"
        file.write_text(source, encoding="utf-8")
        arguments += ["--input", "-" if stdin else str(file)]
    result = runner.invoke(app, [*arguments, "--json"], input=source if stdin else None)
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {"Name": "Æble", "ContactGuid": "guid"}
    assert not result.stderr and len(requests) == 1
    request = requests[0]
    assert request.method == method.upper() and request.url.path == "/v1/456/contacts"
    assert parse_qsl(request.url.query.decode(), keep_blank_values=True) == pairs
    assert request.headers["Authorization"] == "Bearer sentinel-access-token"
    assert request.headers["Accept"] == "application/json"
    assert (json.loads(request.content) if request.content else None) == (
        None if method == "get" else payload
    )


def test_explicit_path_is_unchanged_and_human_default(wire):
    runner, requests, _ = wire
    result = runner.invoke(app, ["api", "get", "/v1/789/contacts", "--organization", "456"])
    assert result.exit_code == 0 and "Æble" in result.stdout and "ContactGuid" in result.stdout
    assert requests[0].url.path == "/v1/789/contacts"
    with pytest.raises(ValueError):
        json.loads(result.stdout)


@pytest.mark.parametrize("payload", [None, [], {}, [1, {"Name": "Æble"}], "scalar", 0, False])
def test_json_response_shapes_and_preference(wire, payload):
    runner, _, responses = wire
    save_setting("output", "json")
    responses[0] = httpx.Response(204) if payload is None else httpx.Response(200, json=payload)
    result = runner.invoke(app, ["api", "get", "/v1/organizations"])
    assert result.exit_code == 0 and not result.stderr
    assert json.loads(result.stdout) == payload


@pytest.mark.parametrize(
    "args",
    [
        ["get", "https://elsewhere.example/v1"],
        ["get", "/v1/../secret"],
        ["get", "/v1/contacts?x=1"],
        ["get", "/v1/contacts", "--query", "missing-equals"],
        ["get", "/v1/contacts", "--query", "=empty-key"],
        ["get", "/v1/contacts", "--input", "-"],
        ["post", "/v1/contacts", "--input", "-"],
    ],
)
def test_invalid_input_does_not_read_credentials_or_send(wire, monkeypatch, args):
    from dinero_cli.auth import AuthService

    def forbidden(*args):
        pytest.fail("Invalid input must fail before credentials or network")

    monkeypatch.setattr(AuthService, "credentials", forbidden)
    runner, requests, _ = wire
    result = runner.invoke(app, ["api", *args, "--json"], input='{"Name":NaN}')
    assert result.exit_code == 2 and not result.stdout and not requests
    assert json.loads(result.stderr)["error"] is True


@pytest.mark.parametrize("status,code", [(400, 4), (401, 3), (403, 4), (429, 6), (500, 4)])
def test_http_errors_preserve_status_redact_and_never_retry(wire, status, code):
    runner, requests, responses = wire
    responses[0] = httpx.Response(
        status, json={"Message": "Denied sentinel-access-token"}, headers={"Retry-After": "17"}
    )
    result = runner.invoke(app, ["api", "post", "/v1/123/contacts", "--json"])
    assert result.exit_code == code and not result.stdout and len(requests) == 1
    error = json.loads(result.stderr)
    assert error["status"] == status and "sentinel" not in result.stderr
    assert error["message"] == "Denied [REDACTED]"
    if status == 429:
        assert error["details"]["retry_after"] == "17"


def test_transport_and_unsupported_response_are_safe(wire):
    runner, requests, responses = wire
    responses[0] = httpx.ReadTimeout("sentinel-client-secret")
    result = runner.invoke(app, ["api", "put", "/v1/123/contacts", "--json"])
    assert (
        result.exit_code == 5 and "uncertain" in result.stderr and "sentinel" not in result.stderr
    )
    assert not result.stdout and len(requests) == 1
    responses[0] = httpx.Response(200, content=b"PDF bytes")
    result = runner.invoke(app, ["api", "get", "/v1/file", "--json"])
    assert result.exit_code == 5 and json.loads(result.stderr)["status"] == 200
    assert not result.stdout and "PDF bytes" not in result.stderr


def test_logout_prevents_api_call(wire):
    runner, requests, _ = wire
    assert runner.invoke(app, ["auth", "logout", "--json"]).exit_code == 0
    result = runner.invoke(app, ["api", "get", "/v1/organizations", "--json"])
    assert result.exit_code == 3 and not result.stdout and not requests
    assert json.loads(result.stderr)["status"] is None
