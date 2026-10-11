"""Native release checks fail on regressions rather than accepting mock success."""

from pathlib import Path

import pytest
from typer.main import get_command

from dinero_cli.cli import app
from scripts.smoke_resources import (
    DOCUMENT,
    DOWNLOAD_FAILURES,
    GUID,
    LOOKUP_VARIANTS,
    NO_SIMILAR,
    resource_cases,
    verify_resources,
)


def test_native_resource_inventory_covers_every_dedicated_leaf():
    root = get_command(app)
    actual = {
        (group, verb)
        for group, command in root.commands.items()
        if group not in ("api", "auth", "config")
        for verb in command.commands
    }
    cases = [(args[0], args[1]) for args, *_ in resource_cases()]
    assert len(cases) == len(set(cases))
    assert set(cases) == actual


@pytest.mark.parametrize(
    "fault",
    [
        "response",
        "count",
        "wire",
        "body",
        "error",
        "uncertain",
        "rate",
        "org",
        "auth",
        "download-bytes",
        "download-overwrite",
        "download-error",
        "download-partial",
        "download-rate",
    ],
)
def test_resource_smoke_rejects_regressions(tmp_path, fault):
    requests = []
    token = "resource-smoke-test-only"
    cases = {tuple(args[:2]): (method, path, body) for args, method, path, body in resource_cases()}

    def invoke(args, code, source):
        if args[:2] == ["config", "get"]:
            return {"organization": "456" if fault == "org" else "123"}
        if args[:2] == ["auth", "status"]:
            return {"authorized": fault != "auth"}
        if args[:2] == ["files", "download"]:
            output = Path(args[args.index("--output") + 1])
            if code == 2:
                if fault == "download-overwrite":
                    output.write_bytes(b"overwritten")
                return {"error": True}
            if args[2] in DOWNLOAD_FAILURES:
                requests.append(("GET", f"/v1/456/files/{args[2]}", b"", "Bearer " + token))
                if fault == "download-partial":
                    output.write_bytes(b"partial")
                return {
                    "error": True,
                    "status": 0 if fault == "download-error" else DOWNLOAD_FAILURES[args[2]][1],
                    "details": {"retry_after": "0" if fault == "download-rate" else "17"},
                }
            output.write_bytes(b"wrong" if fault == "download-bytes" else DOCUMENT)
        method, path, _ = cases[tuple(args[:2])]
        if args[:2] == ["purchase-vouchers", "get-by-file"]:
            path = f"/v1/456/vouchers/purchase/fileguid/{args[2]}"
        if "--input" in args:
            filename = args[args.index("--input") + 1]
            if filename != "-":
                source = Path(filename).read_text(encoding="utf-8")
        raw = source.encode() if source is not None else b""
        requests.append(
            (
                "WRONG" if fault == "wire" else method,
                path,
                b"{}" if fault == "body" else raw,
                "Bearer " + token,
            )
        )
        if fault == "count":
            requests.append(requests[-1])
        if code:
            return {
                "error": True,
                "status": 0 if fault == "error" else {4: 409, 6: 429, 5: None}[code],
                "message": "uncertain" if fault != "uncertain" else "failure",
                "details": {"retry_after": "0" if fault == "rate" else "17"},
            }
        if fault != "response":
            if args[:2] == ["files", "download"]:
                return {"path": str(output), "bytes": len(DOCUMENT)}
            if args[:2] == ["purchase-vouchers", "get-by-file"]:
                return LOOKUP_VARIANTS.get(args[2], [GUID])
            if args[:2] == ["purchase-vouchers", "similar"]:
                if source is not None and "__smoke_no_similar" in source:
                    return NO_SIMILAR
                return {"SimilarFound": True, "SimilarGuid": GUID, "VoucherNumber": 17}
        return (
            "changed" if fault == "response" else None if method == "DELETE" else {"Name": "Æble"}
        )

    expected = {
        "response": "response fidelity",
        "count": "hidden request or retry",
        "wire": "method, path or authorization",
        "body": "payload fidelity",
        "error": "mutation error or replay",
        "uncertain": "uncertain write diagnostic",
        "rate": "rate limit detail",
        "org": "organization override persisted",
        "auth": "local auth status",
        "download-bytes": "download bytes",
        "download-overwrite": "download overwrite",
        "download-error": "download error or retry",
        "download-partial": "partial download",
        "download-rate": "download rate limit",
    }
    with pytest.raises(ValueError, match="Native resource smoke failed: " + expected[fault]):
        verify_resources(invoke, str(tmp_path), requests, token, {"Name": "Æble"})
