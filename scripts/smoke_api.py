"""Exercise native binaries against a private local HTTPS fixture, never live Dinero."""

import json
import shutil
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from dinero_cli.auth import TokenRecord
from dinero_cli.config import Settings
from dinero_cli.secrets import SecretStore
from dinero_cli.storage import atomic_write

TOKEN = "native-smoke-access-token"
PAYLOAD = {"ContactGuid": "fixture", "Lines": [{"Description": "Æble", "Amount": 12.5}]}


def make_certificate(directory: Path) -> tuple[Path, Path]:
    """Require build-host OpenSSL to create a one-day, local-only test certificate."""
    executable = shutil.which("openssl")
    if executable is None:
        raise ValueError("Native API smoke requires OpenSSL on the build host PATH")
    certificate, private_key = directory / "ca.pem", directory / "key.pem"
    configuration = directory / "openssl.cnf"
    configuration.write_text(
        "[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=server\n"
        "[dn]\nCN=Dinero local smoke test\n"
        "[server]\nbasicConstraints=critical,CA:TRUE\n"
        "keyUsage=critical,digitalSignature,keyCertSign\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n",
        encoding="ascii",
    )
    subprocess.run(
        [
            executable,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-config",
            str(configuration),
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return certificate, private_key


def smoke_api(executable: Path, environment: dict[str, str], directory: str) -> None:
    """Verify TLS, bearer auth, JSON writes, errors and logout in an isolated native process."""
    requests: list[tuple[str, str, bytes, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Test credentials and request contents must not enter build logs.

        def respond(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append((self.command, self.path, body, self.headers.get("Authorization")))
            status = (
                400
                if self.path.endswith("/error")
                else 429
                if self.path.endswith("/rate")
                else 204
                if self.command == "DELETE"
                else 200
            )
            value: Any = (
                {"Message": "Rejected " + TOKEN}
                if status == 400
                else {"Message": "Limited"}
                if status == 429
                else PAYLOAD
            )
            raw = (
                b"not JSON"
                if self.path.endswith("/binary")
                else b""
                if status == 204
                else json.dumps(value).encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if status == 429:
                self.send_header("Retry-After", "17")
            self.end_headers()
            self.wfile.write(raw)

        do_GET = respond
        do_POST = respond
        do_PUT = respond
        do_DELETE = respond

    certificate, private_key = make_certificate(Path(directory))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, private_key)
    environment = {**environment, "SSL_CERT_FILE": str(certificate)}
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.socket = context.wrap_socket(server.socket, server_side=True)
        origin = f"https://127.0.0.1:{server.server_port}"
        settings = Settings(
            client_id="native-smoke-client",
            credential_backend="file",
            organization="123",
            api_base_url=origin,
            trusted_api_origins=[origin],
        )
        state = Path(environment["DINERO_CONFIG_DIR"])
        atomic_write(state / "config.json", settings.model_dump_json().encode())
        with SecretStore(settings, state).transaction() as transaction:
            transaction.state.client_secret = SecretStr("native-smoke-client-secret")
            transaction.state.tokens = TokenRecord(
                access_token=SecretStr(TOKEN),
                expires_at=time.time() + 3600,
                client_id="native-smoke-client",
                api_origin=origin,
            ).storage()
            transaction.save()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            verify_flow(executable, environment, directory, requests)
        finally:
            server.shutdown()
            worker.join(timeout=5)


def verify_flow(
    executable: Path,
    environment: dict[str, str],
    directory: str,
    requests: list[tuple[str, str, bytes, str | None]],
) -> None:
    """Check process outputs and captured wire requests; every mismatch fails the build."""

    def invoke(arguments: list[str], code: int = 0, payload: str | None = None) -> Any:
        result = subprocess.run(
            [str(executable.resolve()), *arguments, "--json"],
            cwd=directory,
            env=environment,
            input=payload,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=45,
            check=False,
        )
        if result.returncode != code or (result.stderr if code == 0 else result.stdout):
            raise ValueError("Native API smoke failed: process status or output stream")
        if any(
            secret in result.stdout + result.stderr
            for secret in (TOKEN, "native-smoke-client-secret")
        ):
            raise ValueError("Native API smoke failed: credential output")
        return json.loads(result.stdout if code == 0 else result.stderr)

    path = "/v1/{organizationId}/contacts"
    for verb in ("get", "post", "put", "delete"):
        arguments = [
            "api",
            verb,
            path,
            "--query",
            "fields=Name",
            "--query",
            "x=Æ &",
            "--query",
            "fields=Email",
        ]
        body = None
        if verb in {"post", "put"}:
            arguments += ["--input", "-"]
            body = json.dumps(PAYLOAD, ensure_ascii=False)
        result = invoke(arguments, payload=body)
        if result != (None if verb == "delete" else PAYLOAD):
            raise ValueError("Native API smoke failed: response fidelity")
        method, url, raw, authorization = requests[-1]
        if (method, url, authorization) != (
            verb.upper(),
            "/v1/123/contacts?fields=Name&x=%C3%86+%26&fields=Email",
            "Bearer " + TOKEN,
        ):
            raise ValueError("Native API smoke failed: method, URL or authorization")
        if (json.loads(raw) if raw else None) != (PAYLOAD if body else None):
            raise ValueError("Native API smoke failed: request body")
    for endpoint, code, status in (("error", 4, 400), ("rate", 6, 429), ("binary", 5, 200)):
        error = invoke(["api", "get", f"/v1/123/{endpoint}"], code)
        if error["error"] is not True or error["status"] != status:
            raise ValueError("Native API smoke failed: error contract")
        if status == 429 and error["details"].get("retry_after") != "17":
            raise ValueError("Native API smoke failed: rate limit details")
    invoke(["api", "post", path, "--input", "-"], 2, '{"Name":NaN}')
    invoke(["api", "get", "https://elsewhere.invalid/"], 2)
    invoke(["auth", "logout"])
    invoke(["api", "get", path], 3)
    if len(requests) != 7:
        raise ValueError("Native API smoke failed: unexpected request or retry")
