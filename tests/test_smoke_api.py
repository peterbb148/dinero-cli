"""Run the native smoke scenario against the real CLI/TLS stack for measured coverage."""

import json
import os
import subprocess

import pytest
from typer.testing import CliRunner

from dinero_cli.cli import app
from scripts import smoke_api


def test_https_smoke_uses_real_cli_auth_and_server(tmp_path, monkeypatch):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("DINERO_")}
    for key in list(os.environ):
        if key.startswith("DINERO_"):
            monkeypatch.delenv(key)
    environment.update(PATH="", DINERO_CONFIG_DIR=str(tmp_path / "state"))
    calls = []
    native_run = subprocess.run

    def execute(arguments, **kwargs):
        if arguments[1] == "req":
            return native_run(arguments, **kwargs)
        calls.append(arguments)
        assert kwargs["env"]["PATH"] == "" and kwargs["encoding"] == "utf-8"
        assert kwargs["timeout"] == 45
        result = CliRunner().invoke(app, arguments[1:], env=kwargs["env"], input=kwargs["input"])
        return subprocess.CompletedProcess(
            arguments, result.exit_code, result.stdout, result.stderr
        )

    monkeypatch.setattr(smoke_api.subprocess, "run", execute)
    smoke_api.smoke_api(tmp_path / "dinero", environment, str(tmp_path))
    assert len(calls) == 11 + 31 + 13 + 12 + 2


@pytest.mark.parametrize(
    "fault", ["status", "stream", "secret", "response", "wire", "body", "error", "rate", "count"]
)
def test_smoke_fails_on_contract_regression(tmp_path, monkeypatch, fault):
    requests = []
    monkeypatch.setattr(smoke_api, "verify_resources", lambda *args: 0)

    def execute(arguments, **kwargs):
        verb = arguments[2]
        path = arguments[3] if len(arguments) > 3 else ""
        code = 0
        value = smoke_api.PAYLOAD
        if "elsewhere" in path or kwargs["input"] == '{"Name":NaN}':
            code, value = 2, {"error": True}
        elif verb == "logout":
            value = {"logged_out": True}
        elif len(requests) >= 7:
            code, value = 3, {"error": True}
        elif path.endswith(("error", "rate", "binary")):
            code, status = (
                (4, 400)
                if path.endswith("error")
                else (6, 429)
                if path.endswith("rate")
                else (5, 200)
            )
            value = {
                "error": True,
                "status": 0 if fault == "error" else status,
                "details": {"retry_after": "0" if fault == "rate" else "17"},
            }
            requests.append(("GET", path, b"", "Bearer " + smoke_api.TOKEN))
        else:
            value = None if verb == "delete" else smoke_api.PAYLOAD
            raw = kwargs["input"].encode() if kwargs["input"] else b""
            requests.append(
                (
                    "WRONG" if fault == "wire" else verb.upper(),
                    "/v1/123/contacts?fields=Name&x=%C3%86+%26&fields=Email",
                    b"{}" if fault == "body" else raw,
                    "Bearer " + smoke_api.TOKEN,
                )
            )
        if fault == "count" and verb == "logout":
            requests.append(("GET", "/extra", b"", None))
        if fault == "response":
            value = "changed"
        if fault == "secret":
            value = smoke_api.TOKEN
        out = json.dumps(value)
        return subprocess.CompletedProcess(
            arguments,
            99 if fault == "status" else code,
            out if code == 0 else "",
            out if fault == "stream" or code else "",
        )

    monkeypatch.setattr(smoke_api.subprocess, "run", execute)
    with pytest.raises(ValueError, match="Native API smoke failed"):
        smoke_api.verify_flow(tmp_path / "dinero", {}, str(tmp_path), requests)


def test_certificate_requires_openssl(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke_api.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="requires OpenSSL"):
        smoke_api.make_certificate(tmp_path)
