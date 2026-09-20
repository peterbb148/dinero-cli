"""Offline OAuth grants, exact request construction and serialized refresh safety."""

import base64
import hashlib
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from dinero_cli import auth, secrets
from dinero_cli.config import Settings
from dinero_cli.errors import CLIError


@pytest.fixture
def service(tmp_path):
    settings = Settings(client_id="registered-app", credential_backend="file")
    store = secrets.SecretStore(settings, tmp_path / "state")
    with store.transaction() as txn:
        txn.state.client_secret = SecretStr("sentinel-client-secret")
        txn.save()
    return auth.AuthService(settings, store=store, now=lambda: 1000)


def grant(**changes):
    return {
        "access_token": "sentinel-access",
        "refresh_token": "sentinel-refresh",
        "token_type": "Bearer",
        "expires_in": 3600,
        **changes,
    }


def token(service, *, expired=False, **changes):
    with service.store.transaction() as txn:
        txn.state.tokens = {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_at": 900 if expired else 9000,
            "client_id": "registered-app",
            "api_origin": "https://api.dinero.dk:443",
            **changes,
        }
        txn.save()


@pytest.mark.parametrize("pkce", [False, True])
def test_login_exact_protocol_and_safe_status(service, pkce):
    service.settings.pkce = pkce
    params = {}

    def callback(url, state):
        params.update(parse_qs(urlsplit(url).query))
        assert url.startswith(auth.AUTHORIZE + "?")
        assert params["state"] == [state] and len(state) >= 32
        assert params["response_mode"] == ["form_post"]
        assert "organization" not in params
        return "sentinel-code"

    def respond(request):
        assert str(request.url) == auth.TOKEN
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        fields = parse_qs(request.content.decode())
        assert fields["code"] == ["sentinel-code"]
        assert fields["client_secret"] == ["sentinel-client-secret"]
        assert fields["redirect_uri"] == [service.settings.redirect_uri]
        if pkce:
            digest = hashlib.sha256(fields["code_verifier"][0].encode()).digest()
            assert params["code_challenge"] == [
                base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            ]
            assert params["code_challenge_method"] == ["S256"]
        else:
            assert "code_verifier" not in fields and "code_challenge" not in params
        return httpx.Response(200, json=grant(id_token="must-be-discarded"))

    service.transport = httpx.MockTransport(respond)
    result = service.login(callback)
    assert result == {
        "authorized": True,
        "access_token_valid": True,
        "refresh_available": True,
        "expires_at": 4600,
        "configuration_matches": True,
        "refresh_pending": False,
    }
    assert "sentinel" not in repr(result)
    with service.store.transaction() as txn:
        assert "id_token" not in txn.state.tokens
        assert txn.state.tokens["access_token"] == "sentinel-access"
    assert service.access_token() == "sentinel-access"
    assert service.logout() == {"logged_out": True}
    assert not service.status()["authorized"]
    with service.store.transaction() as txn:
        assert txn.state.client_secret.get_secret_value() == "sentinel-client-secret"


def test_status_without_backend_is_read_only(tmp_path, monkeypatch):
    directory = tmp_path / "absent"
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(directory))
    result = auth.AuthService(Settings()).status()
    assert not result["authorized"] and result["expires_at"] is None
    assert not directory.exists()


@pytest.mark.parametrize(
    "change", [{}, {"api_origin": "https://different.example:443"}, {"client_id": "another"}]
)
def test_missing_or_mismatched_authorization(service, change):
    if change:
        token(service, **change)
    with pytest.raises(CLIError, match="missing or its context changed"):
        service.access_token()


def test_untrusted_origin_and_missing_client_fail_before_store(service, monkeypatch):
    monkeypatch.setattr(service, "secret_store", lambda: pytest.fail("Must not read credentials"))
    service.settings.api_base_url = "https://other.example:443"
    with pytest.raises(CLIError, match="allowlist"):
        service.access_token()
    service.settings.api_base_url = "https://api.dinero.dk:443"
    service.settings.client_id = None
    with pytest.raises(CLIError, match="client-id"):
        service.login(lambda *a: pytest.fail("No browser"))


@pytest.mark.parametrize("refresh", [None, "old-refresh"])
def test_refresh_requires_token_and_client_secret(service, refresh):
    token(service, expired=True, refresh_token=refresh)
    if refresh:
        with service.store.transaction() as txn:
            txn.state.client_secret = None
            txn.save()
    with pytest.raises(CLIError, match="cannot be refreshed"):
        service.access_token()


@pytest.mark.parametrize("rotated", [None, "new-refresh"])
def test_refresh_rotation_and_reusable_token_response(service, rotated):
    token(service, expired=True)
    count = []

    def respond(request):
        count.append(1)
        fields = parse_qs(request.content.decode())
        assert fields["grant_type"] == ["refresh_token"]
        assert fields["refresh_token"] == ["old-refresh"]
        return httpx.Response(200, json=grant(refresh_token=rotated))

    service.transport = httpx.MockTransport(respond)
    assert service.access_token() == "sentinel-access"
    assert service.access_token() == "sentinel-access" and len(count) == 1
    with service.store.transaction() as txn:
        assert txn.state.tokens["refresh_token"] == (rotated or "old-refresh")
        assert not txn.state.refresh_pending


def test_failed_refresh_is_not_replayed(service):
    token(service, expired=True)
    count = []

    def respond(request):
        count.append(1)
        raise httpx.ReadTimeout("sentinel-client-secret")

    service.transport = httpx.MockTransport(respond)
    with pytest.raises(CLIError) as failure:
        service.access_token()
    assert "sentinel" not in str(failure.value)
    with pytest.raises(CLIError, match="Previous token refresh"):
        service.access_token()
    assert len(count) == 1 and service.status()["refresh_pending"]


@pytest.mark.parametrize("after_exchange", [False, True])
def test_failed_save_prevents_reuse_or_network(service, monkeypatch, after_exchange):
    token(service, expired=True)
    calls = []
    service.transport = httpx.MockTransport(
        lambda request: (calls.append(1), httpx.Response(200, json=grant()))[1]
    )
    original = secrets.Transaction.save
    saves = []

    def fail(txn):
        saves.append(1)
        if len(saves) == (2 if after_exchange else 1):
            raise OSError("sentinel-access")
        original(txn)

    with monkeypatch.context() as patch:
        patch.setattr(secrets.Transaction, "save", fail)
        with pytest.raises(OSError):
            service.access_token()
    assert len(calls) == int(after_exchange)
    if after_exchange:
        with pytest.raises(CLIError, match="Previous token refresh"):
            service.access_token()


@pytest.mark.parametrize(
    "payload",
    [
        grant(access_token=""),
        grant(access_token="a\nb"),
        grant(access_token="æ"),
        grant(token_type="DPoP"),
        grant(expires_in=0),
        {"client_secret": "sentinel"},
    ],
)
def test_invalid_token_grants_are_sanitized(service, payload):
    service.transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(CLIError) as failure:
        service.exchange({})
    assert failure.value.status == 200 and "sentinel" not in str(failure.value)


@pytest.mark.parametrize("status", [302, 400, 401, 429, 500])
def test_provider_error_preserves_status_without_remote_secrets(service, status):
    service.transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text="sentinel-access")
    )
    with pytest.raises(CLIError) as failure:
        service.exchange({})
    assert failure.value.code == 3 and failure.value.status == status
    assert "sentinel" not in str(failure.value)


def test_malformed_stored_record_and_missing_secret(service):
    with service.store.transaction() as txn:
        txn.state.tokens = {"secret": "sentinel"}
        txn.save()
    with pytest.raises(CLIError, match="Stored authorization"):
        service.status()
    with service.store.transaction() as txn:
        txn.state.tokens = None
        txn.state.client_secret = None
        txn.save()
    with pytest.raises(CLIError, match="Store the Visma"):
        service.login(lambda *args: pytest.fail("No callback"))


def test_client_secret_removed_during_consent(service):
    def callback(*args):
        with service.store.transaction() as txn:
            txn.state.client_secret = None
            txn.save()
        return "code"

    with pytest.raises(CLIError, match="removed during login"):
        service.login(callback)


def test_parallel_processes_exchange_a_single_refresh_token(service, tmp_path):
    token(service, expired=True)
    calls = tmp_path / "calls"
    code = """
import sys,time
from pathlib import Path
import httpx
from dinero_cli.auth import AuthService
from dinero_cli.config import Settings
from dinero_cli.secrets import SecretStore
settings=Settings(client_id="registered-app",credential_backend="file")
def exchange(request):
    with Path(sys.argv[2]).open("a") as f: f.write("exchange\\n")
    time.sleep(0.1)
    return httpx.Response(200,json={
        "access_token":"new-access", "refresh_token":"new-refresh",
        "token_type":"Bearer", "expires_in":3600})
service=AuthService(settings,store=SecretStore(settings,Path(sys.argv[1])),transport=httpx.MockTransport(exchange),now=lambda:1000)
assert service.access_token()=="new-access"
"""
    workers = [
        subprocess.Popen([sys.executable, "-c", code, str(service.store.directory), str(calls)])
        for _ in range(4)
    ]
    assert [worker.wait(timeout=20) for worker in workers] == [0] * 4
    assert calls.read_text() == "exchange\n"
