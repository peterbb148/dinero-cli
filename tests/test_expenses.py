"""Verify expense reads, streaming download fidelity and no partial or overwritten files."""

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from typer.testing import CliRunner

from dinero_cli.auth import Credentials
from dinero_cli.cli import app
from dinero_cli.client import APIClient
from dinero_cli.commands import resources
from dinero_cli.config import Settings
from dinero_cli.downloads import DownloadFile
from dinero_cli.errors import CLIError

GUID = "cdb485f3-a188-48b1-8d40-f6c8014c9f21"
FILE_ID = "fixturefileid1234567890abcdefghij"
OTHER = "ddb485f3-a188-48b1-8d40-f6c8014c9f21"
SECRET = "expense-token / +"


class Auth:
    def credentials(self):
        return Credentials("expense-token", (SECRET,), organization="456")


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, fail=None):
        self.chunks = chunks
        self.fail = fail
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise self.fail

    async def aclose(self):
        self.closed = True


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(tmp_path / "state"))
    for key in Settings.model_fields:
        monkeypatch.delenv("DINERO_" + key.upper(), raising=False)
    calls = []

    def install(response):
        def respond(request):
            calls.append(request)
            return response(request) if callable(response) else response

        monkeypatch.setattr(
            resources,
            "APIClient",
            lambda settings: APIClient(
                settings, auth=Auth(), transport=httpx.MockTransport(respond)
            ),
        )

    return CliRunner(), calls, install


@pytest.mark.parametrize("file_id", [FILE_ID, GUID, GUID.upper(), "opaque+\u00c6=ID"])
@pytest.mark.parametrize("value", [[], [GUID], [GUID, OTHER]])
def test_get_by_file_keeps_every_guid(wire, value, file_id):
    runner, calls, install = wire
    install(httpx.Response(200, json=value))
    result = runner.invoke(
        app, ["purchase-vouchers", "get-by-file", file_id, "--organization", "456", "--json"]
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == value
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert (
        calls[0].url.raw_path
        == f"/v1/456/vouchers/purchase/fileguid/{quote(file_id, safe='')}".encode()
    )
    assert calls[0].content == b""


@pytest.mark.parametrize("stdin", [False, True])
@pytest.mark.parametrize("found", [False, True])
def test_similar_preserves_payload_and_response(wire, tmp_path, stdin, found):
    runner, calls, install = wire
    value = {
        "SimilarFound": found,
        "SimilarGuid": GUID if found else None,
        "VoucherNumber": 17 if found else None,
        "Future": [1, None],
    }
    install(httpx.Response(200, json=value))
    body = {
        "PurchaseType": "cash",
        "Lines": [{"Amount": 125, "Description": "Æble"}],
        "Future": {"x": False},
    }
    source = json.dumps(body, ensure_ascii=False)
    path = tmp_path / "similar.json"
    path.write_text(source, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "purchase-vouchers",
            "similar",
            "--input",
            "-" if stdin else str(path),
            "--organization",
            "456",
            "--json",
        ],
        input=source if stdin else None,
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == value
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].url.path == "/v1/456/vouchers/purchase/similar"
    assert json.loads(calls[0].content) == body


@pytest.mark.parametrize(
    "source",
    [
        "{}",
        '{"PurchaseType":"cash","PurchaseType":"credit"}',
        '{"PurchaseType":"cash","Lines":[{"Amount":"125"}]}',
        "[]",
        '{"PurchaseType":"cash","Amount":NaN}',
    ],
)
def test_similar_invalid_payload_never_sends(wire, source):
    runner, calls, install = wire
    install(httpx.Response(200))
    result = runner.invoke(
        app,
        ["purchase-vouchers", "similar", "--input", "-", "--organization", "456", "--json"],
        input=source,
    )
    assert result.exit_code == 2
    assert not calls and not result.stdout


@pytest.mark.parametrize(
    "data", [b"", b"%PDF-1.7\x00\xff\n", bytes(range(256)) * 4096], ids=["empty", "pdf", "large"]
)
@pytest.mark.parametrize("file_id", [FILE_ID, GUID, GUID.upper(), "opaque+\u00c6=ID"])
def test_download_streams_original_bytes(wire, tmp_path, data, file_id):
    runner, calls, install = wire
    target = tmp_path / "bilag Æ.bin"

    def chunks():
        for offset in range(0, len(data), 4096):
            assert not target.exists()
            yield data[offset : offset + 4096]

    stream = Chunks(chunks())
    install(
        httpx.Response(
            200,
            stream=stream,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="../../bad.exe"',
            },
        )
    )
    result = runner.invoke(
        app,
        ["files", "download", file_id, "--output", str(target), "--organization", "456", "--json"],
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {"path": str(target), "bytes": len(data)}
    assert target.read_bytes() == data and stream.closed
    assert len(calls) == 1
    assert calls[0].url.raw_path == f"/v1/456/files/{quote(file_id, safe='')}".encode()
    assert calls[0].headers["Authorization"] == "Bearer expense-token"
    assert calls[0].headers["Accept"] == "*/*"
    assert not list(tmp_path.glob(".dinero-download-*"))


@pytest.mark.parametrize(
    "status,code", [(302, 4), (400, 4), (401, 3), (403, 4), (429, 6), (500, 4)]
)
def test_download_http_error_leaves_no_file_and_redacts(wire, tmp_path, status, code):
    runner, calls, install = wire
    install(
        httpx.Response(
            status,
            json={"Message": SECRET},
            headers={"Retry-After": "17", "Location": "https://elsewhere.invalid"},
        )
    )
    target = tmp_path / "failed.bin"
    result = runner.invoke(
        app, ["files", "download", GUID, "--output", str(target), "--organization", "456", "--json"]
    )
    assert result.exit_code == code and not result.stdout
    error = json.loads(result.stderr)
    assert error["status"] == status
    assert SECRET not in result.stderr
    if status == 429:
        assert error["details"]["retry_after"] == "17"
    assert len(calls) == 1 and not target.exists()
    assert not list(tmp_path.glob(".dinero-download-*"))


@pytest.mark.parametrize(
    "failure,code", [(httpx.ReadError("private detail"), 5), (KeyboardInterrupt(), 130)]
)
def test_interrupted_download_removes_partial(wire, tmp_path, failure, code):
    runner, calls, install = wire
    stream = Chunks([b"partial"], failure)
    install(httpx.Response(200, stream=stream))
    target = tmp_path / "failed.bin"
    result = runner.invoke(
        app, ["files", "download", GUID, "--output", str(target), "--organization", "456", "--json"]
    )
    assert result.exit_code == code and not result.stdout
    assert not target.exists() and stream.closed
    assert not list(tmp_path.glob(".dinero-download-*"))
    assert len(calls) == 1


@pytest.mark.parametrize("encoded", [False, True])
def test_credential_echo_crossing_chunks_is_not_saved(wire, tmp_path, encoded):
    runner, calls, install = wire
    secret = (quote(SECRET, safe="") if encoded else SECRET).encode()
    install(httpx.Response(200, stream=Chunks([b"prefix" + secret[:5], secret[5:] + b"suffix"])))
    target = tmp_path / "failed.bin"
    result = runner.invoke(
        app, ["files", "download", GUID, "--output", str(target), "--organization", "456", "--json"]
    )
    assert result.exit_code == 5 and not result.stdout
    assert "credential data" in result.stderr and SECRET not in result.stderr
    assert not target.exists() and not list(tmp_path.glob(".dinero-download-*"))


@pytest.mark.parametrize(
    "kind,code",
    [
        ("existing", 2),
        ("directory", 2),
        ("missing-parent", 5),
        ("stdout", 2),
        ("no-org", 2),
        ("wrong-org", 3),
    ],
)
def test_download_invalid_destination_or_org(wire, tmp_path, kind, code):
    runner, calls, install = wire
    install(httpx.Response(200, content=b"new"))
    target = tmp_path / "receipt.bin"
    if kind == "existing":
        target.write_bytes(b"original")
    if kind == "directory":
        target.mkdir()
    if kind == "missing-parent":
        target = tmp_path / "missing" / "receipt.bin"
    args = [
        "files",
        "download",
        GUID,
        "--output",
        "-" if kind == "stdout" else str(target),
        "--json",
    ]
    if kind != "no-org":
        args += ["--organization", "123" if kind == "wrong-org" else "456"]
    result = runner.invoke(app, args)
    assert result.exit_code == code and not result.stdout
    assert not calls
    if kind == "existing":
        assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".dinero-download-*"))


def test_atomic_publication_refuses_concurrent_destination(wire, tmp_path):
    runner, calls, install = wire
    target = tmp_path / "race.bin"

    def respond(request):
        target.write_bytes(b"another process")
        return httpx.Response(200, content=b"download")

    install(respond)
    result = runner.invoke(
        app, ["files", "download", GUID, "--output", str(target), "--organization", "456", "--json"]
    )
    assert result.exit_code == 2
    assert target.read_bytes() == b"another process"
    assert not list(tmp_path.glob(".dinero-download-*"))


@pytest.mark.parametrize("operation", ["fsync", "link"])
def test_publication_io_failure_cleans_up(tmp_path, monkeypatch, operation):
    import dinero_cli.downloads as downloads

    def fail(*args):
        raise OSError("sensitive local detail")

    monkeypatch.setattr(downloads.os, operation, fail)
    target = tmp_path / "receipt.bin"
    with pytest.raises(CLIError) as failure:
        with DownloadFile(target) as download:
            download.write(b"data")
            download.publish()
    assert failure.value.code == 5
    assert ("finalize" if operation == "fsync" else "publish") in failure.value.message
    assert not list(tmp_path.iterdir())


def test_download_untrusted_origin_before_auth(tmp_path):
    client = APIClient(
        Settings(organization="456", api_base_url="https://elsewhere.invalid"), auth=Auth()
    )
    with pytest.raises(CLIError, match="allowlist"):
        asyncio.run(client.download(f"/v1/456/files/{GUID}", tmp_path / "receipt.bin"))
    assert not list(tmp_path.iterdir())


def test_partial_response_not_published(wire, tmp_path):
    runner, calls, install = wire
    install(httpx.Response(206, content=b"fragment"))
    target = tmp_path / "partial.bin"
    result = runner.invoke(
        app, ["files", "download", GUID, "--output", str(target), "--organization", "456", "--json"]
    )
    assert result.exit_code == 5
    assert json.loads(result.stderr)["status"] == 206
    assert not target.exists() and not list(tmp_path.glob(".dinero-download-*"))


def test_open_failure_closes_and_removes_temporary(tmp_path, monkeypatch):
    import dinero_cli.downloads as downloads

    def fail(*args):
        raise OSError("private path")

    monkeypatch.setattr(downloads.os, "fdopen", fail)
    with pytest.raises(CLIError, match="Unable to create"):
        with DownloadFile(tmp_path / "receipt.bin"):
            pytest.fail("must not enter")
    assert not list(tmp_path.iterdir())


def test_disk_write_failure_removes_temporary(tmp_path):
    class FullDisk:
        def write(self, data):
            raise OSError("private disk error")

        def close(self):
            pass

    with pytest.raises(CLIError, match="Unable to write"):
        with DownloadFile(tmp_path / "receipt.bin") as download:
            download.stream.close()
            download.stream = FullDisk()
            download.write(b"data")
    assert not list(tmp_path.iterdir())


def test_dangling_destination_link_is_refused(tmp_path, monkeypatch):
    target = tmp_path / "receipt.bin"
    # Windows symlink creation can require elevation. Simulate the leaf's lstat
    # result while testing the production no-clobber guard without changing policy.
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(CLIError, match="already exists"):
        with DownloadFile(target):
            pytest.fail("must not enter")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("command", [("files", "download"), ("purchase-vouchers", "get-by-file")])
@pytest.mark.parametrize(
    "file_id",
    [
        "",
        ".",
        "..",
        "a/b",
        "a\\b",
        "a?b",
        "a#b",
        "%2f",
        "%252f",
        "{organizationId}",
        "a b",
        "a\n",
        "a\x00",
        "a\x7f",
        "a\x80",
        "a\x9f",
        "a\ud800",
        "a\udcff",
    ],
)
def test_invalid_file_id_never_sends(wire, tmp_path, command, file_id):
    runner, calls, install = wire
    install(httpx.Response(200))
    target = tmp_path / "invalid.bin"
    args = [*command, file_id, "--organization", "456", "--json"]
    if command[0] == "files":
        args += ["--output", str(target)]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert not result.stdout and not calls and not target.exists()
    assert json.loads(result.stderr)["error"] is True


def test_voucher_id_still_requires_uuid(wire):
    runner, calls, install = wire
    install(httpx.Response(200))
    result = runner.invoke(
        app, ["purchase-vouchers", "get", FILE_ID, "--organization", "456", "--json"]
    )
    assert result.exit_code == 2
    assert not calls and not result.stdout
