"""Read endpoints preserve dates, flags and exact supported query parameters."""

import json
from urllib.parse import parse_qsl

import pytest
from test_resources import wire as wire

from dinero_cli.cli import app

READS = [
    ("entries", "list", "entries"),
    ("entries", "changes", "entries/changes"),
    ("accounts", "entry", "accounts/entry"),
    ("accounts", "purchase", "accounts/purchase"),
    ("accounts", "deposit", "accounts/deposit"),
    ("accounting-years", "list", "accountingyears"),
    ("vat-types", "list", "vatTypes"),
    ("files", "list", "files"),
]


@pytest.mark.parametrize("group,verb,path", READS)
def test_read_defaults_and_fidelity(wire, group, verb, path):
    runner, calls = wire
    result = runner.invoke(app, [group, verb, "--organization", "123", "--json"])
    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].url.path == "/v1/123/" + path
    assert not calls[0].url.query and not calls[0].content
    assert json.loads(result.stdout) == {"Items": [{"Name": "Æble"}], "Next": "preserved"}


@pytest.mark.parametrize(
    "verb,flags,keys",
    [
        ("list", ["--from-date", "--to-date"], ["fromDate", "toDate"]),
        ("changes", ["--changes-from", "--changes-to"], ["changesFrom", "changesTo"]),
    ],
)
@pytest.mark.parametrize(
    "flag,value", [("--include-primo", "true"), ("--no-include-primo", "false")]
)
def test_entry_filters(wire, verb, flags, keys, flag, value):
    runner, calls = wire
    result = runner.invoke(
        app,
        [
            "entries",
            verb,
            "--organization",
            "123",
            flags[0],
            "2026-01-01",
            flags[1],
            "2026-09-20T12:34:56+02:00",
            flag,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert dict(parse_qsl(calls[0].url.query.decode())) == {
        keys[0]: "2026-01-01",
        keys[1]: "2026-09-20T12:34:56+02:00",
        "includePrimo": value,
    }


@pytest.mark.parametrize("verb", ["entry", "purchase", "deposit"])
def test_account_filters(wire, verb):
    runner, calls = wire
    args = ["accounts", verb, "--organization", "123", "--fields", "AccountNumber,Name,VatCode"]
    if verb == "entry":
        args += ["--category-filter", "Travel Expenses"]
    assert runner.invoke(app, [*args, "--json"]).exit_code == 0
    assert dict(parse_qsl(calls[0].url.query.decode())) == {
        "fields": "AccountNumber,Name,VatCode",
        **({"categoryFilter": "Travel Expenses"} if verb == "entry" else {}),
    }


def test_file_filters(wire):
    runner, calls = wire
    result = runner.invoke(
        app,
        [
            "files",
            "list",
            "--organization",
            "123",
            "--extensions",
            "pdf,jpg",
            "--uploaded-after",
            "2026/01/01",
            "--uploaded-before",
            "2026/09/20",
            "--file-status",
            "Unused",
            "--page",
            "1",
            "--page-size",
            "1000",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1
    assert dict(parse_qsl(calls[0].url.query.decode())) == {
        "extensions": "pdf,jpg",
        "uploadedAfter": "2026/01/01",
        "uploadedBefore": "2026/09/20",
        "fileStatus": "Unused",
        "page": "1",
        "pageSize": "1000",
    }


@pytest.mark.parametrize(
    "args",
    [
        ["entries", "list", "--from-date", "2026-02-30"],
        ["entries", "list", "--from-date", "20260101"],
        ["entries", "changes", "--changes-to", "not-a-date"],
        ["entries", "list", "--include-primo", "--no-include-primo"],
        ["entries", "list", "--page", "1"],
        ["accounts", "purchase", "--category-filter", "Travel Expenses"],
        ["vat-types", "list", "--query-filter", "unknown"],
        ["files", "list", "--uploaded-before", "2026/9/1"],
        ["files", "list", "--uploaded-after", "2026/02/30"],
        ["files", "list", "--file-status", "Draft"],
    ],
)
def test_invalid_read_filters(wire, args):
    runner, calls = wire
    result = runner.invoke(app, [*args, "--organization", "123", "--json"])
    assert result.exit_code == 2 and not calls and not result.stdout
