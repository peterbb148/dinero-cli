"""Native release checks fail on regressions rather than accepting mock success."""

from pathlib import Path

import pytest
from typer.main import get_command

from dinero_cli.cli import app
from scripts.smoke_resources import resource_cases, verify_resources


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
    "fault", ["response", "count", "wire", "body", "error", "uncertain", "rate", "org", "auth"]
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
        method, path, _ = cases[tuple(args[:2])]
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
    }
    with pytest.raises(ValueError, match="Native resource smoke failed: " + expected[fault]):
        verify_resources(invoke, str(tmp_path), requests, token, {"Name": "Æble"})
