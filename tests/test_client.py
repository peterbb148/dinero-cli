"""Wire-level async transport tests; no actual Dinero requests or credentials."""

import asyncio
import json
import threading
from urllib.parse import parse_qsl

import httpx
import pytest

from dinero_cli import client
from dinero_cli.auth import Credentials
from dinero_cli.config import Settings
from dinero_cli.errors import CLIError
from dinero_cli.redaction import contains_known_secret, redact
from dinero_cli.serialization import decode_json


class Auth:
    def __init__(self):
        self.calls = []

    def credentials(self):
        self.calls.append(threading.get_ident())
        return Credentials(
            "sentinel-access-token",
            ("sentinel-access-token", "sentinel-refresh-token", "sentinel-client-secret"),
        )


def api(handler, *, settings=None):
    auth = Auth()
    return client.APIClient(
        settings or Settings(organization="123"), auth=auth, transport=httpx.MockTransport(handler)
    ), auth


def run(instance, method="GET", path="/v1/{organizationId}/contacts", **kwargs):
    return asyncio.run(instance.request(method, path, **kwargs))


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_one_request_exact_method_path_query_body_and_worker_auth(method):
    calls = []
    payload = None if method == "GET" else {"Name": "Æble A/S", "Items": [{"Amount": 1}]}
    query = [("queryFilter", "Name eq 'A&B += æ'"), ("fields", "Name"), ("fields", "Email")]

    def respond(request):
        calls.append(request)
        assert request.method == method
        assert request.url.path == "/v1/123/contacts"
        assert parse_qsl(request.url.query.decode()) == query
        assert request.headers["Authorization"] == "Bearer sentinel-access-token"
        assert request.headers["Accept"] == "application/json"
        assert request.extensions["timeout"] == {"connect": 30, "read": 30, "write": 30, "pool": 30}
        if payload is None:
            assert request.content == b""
        else:
            assert json.loads(request.content) == payload
        return httpx.Response(200, json={"ContactGuid": "guid", "Name": "Æble A/S"})

    instance, auth = api(respond)
    assert run(instance, method, query=query, body=payload) == {
        "ContactGuid": "guid",
        "Name": "Æble A/S",
    }
    assert len(calls) == len(auth.calls) == 1
    assert auth.calls[0] != threading.get_ident()


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        [1, None, {"name": "æ"}],
        None,
        True,
        12,
        1.25,
        "text",
        {"Description": "Bearer of this voucher"},
    ],
)
def test_success_preserves_json_shape(value):
    instance, _ = api(lambda request: httpx.Response(200, json=value))
    assert run(instance) == value


@pytest.mark.parametrize("status", [200, 201, 204])
def test_empty_success_is_null(status):
    instance, _ = api(lambda request: httpx.Response(status, content=b""))
    assert run(instance) is None


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "/\\evil",
        "/v1?token=secret",
        "/v1#fragment",
        "/v1/../x",
        "/v1/./x",
        "/%2e%2e/x",
        "/%252e%252e/x",
        "/%2fevil",
        "/v1/%5cx",
        "/v1/white space",
        "/v1/%0Ax",
        "/v1/{unknown}",
        "/v1/%ZZ",
        "/v1/%FF",
    ],
)
def test_invalid_paths_fail_before_credentials_or_network(path):
    instance, auth = api(lambda request: pytest.fail("No request"))
    with pytest.raises(CLIError) as failure:
        run(instance, path=path)
    assert failure.value.code == 2 and auth.calls == []


def test_organization_and_untrusted_origin_fail_before_auth():
    instance, auth = api(lambda request: pytest.fail("No request"), settings=Settings())
    with pytest.raises(CLIError, match="Select an organization"):
        run(instance)
    instance.settings = Settings(api_base_url="https://other.example")
    with pytest.raises(CLIError, match="allowlist"):
        run(instance, path="/v1/organizations")
    assert not auth.calls


def test_fully_specified_path_does_not_need_or_rewrite_organization():
    seen = []
    instance, _ = api(
        lambda request: (seen.append(request.url.raw_path), httpx.Response(200, json=[]))[1],
        settings=Settings(),
    )
    assert run(instance, path="/v1/999/contacts/%C3%A6") == []
    assert seen == [b"/v1/999/contacts/%C3%A6"]


@pytest.mark.parametrize(
    "method,body",
    [
        ("PATCH", None),
        ("GET", {}),
        ("POST", []),
        ("POST", {"amount": float("nan")}),
        ("POST", {"amount": object()}),
    ],
)
def test_invalid_method_or_payload_is_input_failure(method, body):
    instance, auth = api(lambda request: pytest.fail("No request"))
    with pytest.raises(CLIError) as failure:
        run(instance, method, body=body)
    assert failure.value.code == 2 and not auth.calls


@pytest.mark.parametrize(
    "status,code", [(301, 4), (302, 4), (400, 4), (401, 3), (403, 4), (409, 4), (429, 6), (500, 4)]
)
def test_status_message_details_and_no_redirect_or_retry(status, code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={
                "Message": "Rejected sentinel-access-token",
                "Errors": [{"code": 42, "ClientSecret": "never-echo"}],
            },
            headers={"Location": "https://evil.example", "Retry-After": "60"},
        )

    instance, _ = api(respond)
    with pytest.raises(CLIError) as failure:
        run(instance, "POST", body={"Name": "name"})
    error = failure.value
    assert (error.code, error.status) == (code, status)
    assert error.message == "Rejected [REDACTED]"
    assert error.details["response"]["Errors"] == [{"code": 42, "ClientSecret": "[REDACTED]"}]
    assert ("retry_after" in error.details) == (status == 429)
    if status == 429:
        assert error.details["retry_after"] == "60"
    assert len(calls) == 1
    assert "sentinel" not in str(error.payload()) and "never-echo" not in str(error.payload())


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"quota exceeded",
        b'{"message":"Lower case"}',
        b'{"title":"Problem"}',
        b"7",
        b'{"unknown":"value"}',
    ],
)
def test_unstructured_or_unfamiliar_errors_keep_safe_details(body):
    instance, _ = api(lambda request: httpx.Response(400, content=body))
    with pytest.raises(CLIError) as failure:
        run(instance)
    assert failure.value.status == 400
    assert "response" in failure.value.details
    assert failure.value.message


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
@pytest.mark.parametrize(
    "exception", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError]
)
def test_transport_failure_never_replays_and_marks_uncertain_writes(method, exception):
    calls = []

    def fail(request):
        calls.append(request)
        raise exception("sentinel-access-token")

    instance, _ = api(fail)
    with pytest.raises(CLIError) as failure:
        run(instance, method)
    assert failure.value.code == 5
    assert ("uncertain" in failure.value.message) == (method != "GET")
    assert "sentinel" not in failure.value.message and len(calls) == 1


@pytest.mark.parametrize(
    "body", [b"<html>no</html>", b'{"x":1,"x":2}', b"NaN", b"1e999", b"\xff", b"\xff\xfe{\x00}\x00"]
)
def test_unsupported_success_response_fails_instead_of_fake_json(body):
    instance, _ = api(lambda request: httpx.Response(200, content=body))
    with pytest.raises(CLIError) as failure:
        run(instance)
    assert failure.value.code == 5 and failure.value.status == 200


def test_success_echoing_active_credentials_is_never_returned():
    instance, _ = api(
        lambda request: httpx.Response(200, json={"unexpected": "sentinel-client-secret"})
    )
    with pytest.raises(CLIError, match="credential data"):
        run(instance)


def test_tls_failure_does_not_trigger_auth_or_network(monkeypatch):
    instance, auth = api(lambda request: pytest.fail("No request"))

    def fail():
        raise OSError("sensitive file path")

    monkeypatch.setattr(client.ssl, "create_default_context", fail)
    with pytest.raises(CLIError, match="TLS"):
        run(instance)
    assert not auth.calls


def test_origin_is_rechecked_after_request_construction(monkeypatch):
    instance, auth = api(lambda request: pytest.fail("No request"))
    monkeypatch.setattr(
        httpx.AsyncClient,
        "build_request",
        lambda *a, **kw: httpx.Request("GET", "https://evil.example"),
    )
    with pytest.raises(CLIError, match="destination differs"):
        run(instance)
    assert not auth.calls


def test_default_auth_service_is_shared():
    settings = Settings()
    assert client.APIClient(settings).auth.settings is settings


def test_redaction_nested_fields_encoded_values_and_scalar_fidelity():
    secret = "secret&+value"
    value = {
        "nested": [{"Access_Token": "unknown", "text": "secret%26%2Bvalue"}],
        "Authorization": "anything",
        "message": "Bearer unknown-token password=unknown-value",
        "count": 12,
        "nothing": None,
    }
    safe = redact(value, (secret,))
    assert safe["nested"] == [{"Access_Token": "[REDACTED]", "text": "[REDACTED]"}]
    assert safe["Authorization"] == "[REDACTED]"
    assert "unknown" not in safe["message"]
    assert safe["count"] == 12 and safe["nothing"] is None
    assert contains_known_secret([{"field": "secret%26%2Bvalue"}], (secret,))
    assert not contains_known_secret({"Description": "Bearer of voucher", "Count": 12}, (secret,))
    assert redact("unchanged", ("",)) == "unchanged"
    assert "secret" not in repr(Credentials(secret, (secret,)))


def test_strict_json_preserves_finite_floats_and_unicode():
    assert decode_json('{"Name":"Æble","Price":1.5}'.encode()) == {"Name": "Æble", "Price": 1.5}


def test_unstructured_error_redaction_handles_quoted_secret_fields():
    raw = 'broken JSON {"client_secret": "an unknown secret with spaces", password=another}'
    safe = redact(raw, ())
    assert "unknown" not in safe and "another" not in safe
    assert "[REDACTED]" in safe
