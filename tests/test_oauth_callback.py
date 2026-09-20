"""Exercise real loopback callbacks and private-file bootstrap without Visma traffic."""

import socket
import threading
from urllib.parse import urlencode

import httpx
import pytest

from dinero_cli import oauth_callback as callback
from dinero_cli.config import Settings
from dinero_cli.errors import CLIError
from dinero_cli.storage import atomic_write


@pytest.mark.parametrize(
    "raw,message",
    [
        (b"state=wrong&code=sentinel-code", "state mismatch"),
        (b"state=expected&state=expected&code=x", "state mismatch"),
        (b"state=expected&error=access_denied&error_description=sentinel", "denied"),
        (b"state=expected", "valid code"),
        (b"state=expected&code=%0A", "valid code"),
        (b"state=expected&code=%FF", "state mismatch"),
        (b"\xff", "state mismatch"),
        (b"x" * (callback.LIMIT + 1), "state mismatch"),
    ],
)
def test_callback_rejects_untrusted_or_incomplete_fields(raw, message):
    with pytest.raises(CLIError, match=message) as failure:
        callback.authorization_code(raw, "expected")
    assert failure.value.code == 3 and "sentinel" not in str(failure.value)


@pytest.fixture
def settings():
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    return Settings(redirect_uri=f"http://127.0.0.1:{port}/callback")


@pytest.mark.parametrize("mode", ["form_post", "query"])
def test_actual_loopback_callback_is_quiet_and_bounded(settings, monkeypatch, mode, capsys):
    settings.response_mode = mode
    workers = []
    failures = []

    def open_browser(url):
        assert url == "https://connect.visma.com/consent"

        def request():
            try:
                with httpx.Client(trust_env=False, timeout=2) as client:
                    assert client.get(settings.redirect_uri + "/favicon").status_code == 404
                    wrong = client.get if mode == "form_post" else client.post
                    assert wrong(settings.redirect_uri).status_code == 405
                    params = {"state": "expected", "code": "sentinel-code"}
                    response = (
                        client.post(settings.redirect_uri, data=params)
                        if mode == "form_post"
                        else client.get(settings.redirect_uri, params=params)
                    )
                    assert response.status_code == 200
                    assert response.headers["cache-control"] == "no-store"
                    assert "sentinel" not in response.text
            except (AssertionError, httpx.HTTPError) as error:
                failures.append(error)

        worker = threading.Thread(target=request)
        worker.start()
        workers.append(worker)
        return True

    monkeypatch.setattr(callback.webbrowser, "open", open_browser)
    assert (
        callback.collect(settings, "https://connect.visma.com/consent", "expected", timeout=3)
        == "sentinel-code"
    )
    for worker in workers:
        worker.join(timeout=5)
    assert not failures and capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "body,content_type",
    [("bad", "text/plain"), ("state=wrong&code=sentinel", "application/x-www-form-urlencoded")],
)
def test_loopback_invalid_callback_returns_auth_error(settings, monkeypatch, body, content_type):
    workers = []

    def open_browser(url):
        worker = threading.Thread(
            target=lambda: httpx.post(
                settings.redirect_uri,
                content=body,
                headers={"Content-Type": content_type},
                trust_env=False,
            )
        )
        worker.start()
        workers.append(worker)
        return True

    monkeypatch.setattr(callback.webbrowser, "open", open_browser)
    with pytest.raises(CLIError, match="callback"):
        callback.collect(settings, "url", "expected", timeout=3)
    for worker in workers:
        worker.join(timeout=5)


def test_browser_failure_and_loopback_timeout(settings, monkeypatch):
    monkeypatch.setattr(callback.webbrowser, "open", lambda url: False)
    with pytest.raises(CLIError, match="Could not open"):
        callback.collect(settings, "url", "state", timeout=0.01)
    monkeypatch.setattr(callback.webbrowser, "open", lambda url: True)
    with pytest.raises(CLIError, match="timed out"):
        callback.collect(settings, "url", "state", timeout=0.01)


def test_headless_consent_link_requires_private_file(tmp_path):
    with pytest.raises(CLIError, match="requires --authorization-url-file"):
        callback.begin_browser("url", no_browser=True, url_file=None)
    path = tmp_path / "private" / "url"
    callback.begin_browser("consent-link", no_browser=True, url_file=path)
    assert path.read_text() == "consent-link\n"


def test_https_callback_file_flow(settings, tmp_path, monkeypatch):
    settings.redirect_uri = "https://registered.example/callback"
    path = tmp_path / "state" / "callback"
    url_file = tmp_path / "state" / "url"
    original = callback.begin_browser

    def begin(url, **kwargs):
        original(url, **kwargs)
        atomic_write(path, urlencode({"state": "expected", "code": "sentinel-code"}).encode())

    monkeypatch.setattr(callback, "begin_browser", begin)
    assert (
        callback.collect(
            settings,
            "consent-link",
            "expected",
            timeout=1,
            no_browser=True,
            url_file=url_file,
            callback_file=path,
        )
        == "sentinel-code"
    )
    assert url_file.read_text() == "consent-link\n"
    with pytest.raises(CLIError, match="already exists"):
        callback.collect(
            settings,
            "url",
            "state",
            timeout=1,
            no_browser=True,
            url_file=url_file,
            callback_file=path,
        )


def test_callback_configuration_and_file_timeout(settings, tmp_path):
    settings.redirect_uri = "https://registered.example/callback"
    with pytest.raises(CLIError, match="requires --callback-file"):
        callback.collect(settings, "url", "state", timeout=0.01)
    with pytest.raises(CLIError, match="requires --authorization-url-file"):
        callback.collect(
            settings, "url", "state", timeout=0.01, no_browser=True, callback_file=tmp_path / "new"
        )
    with pytest.raises(CLIError, match="timed out"):
        callback.collect(
            settings,
            "url",
            "state",
            timeout=0.01,
            no_browser=True,
            url_file=tmp_path / "state" / "url",
            callback_file=tmp_path / "state" / "new",
        )


def test_registered_https_redirect_validation():
    from dinero_cli.config import validate

    assert validate(
        {"redirect_uri": "https://registered.example/callback"}
    ).redirect_uri.startswith("https:")
    for url in (
        "https://example:0/callback",
        "https://example:invalid/callback",
        "https://example:70000/callback",
    ):
        with pytest.raises(CLIError):
            validate({"redirect_uri": url})
