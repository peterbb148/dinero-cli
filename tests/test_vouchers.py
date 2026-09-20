"""Financial command wire tests prohibit implicit booking, delivery and retries."""

import json
from urllib.parse import parse_qsl

import httpx
import pytest
from test_resources import GUID
from test_resources import wire as wire

from dinero_cli.cli import app
from dinero_cli.client import APIClient
from dinero_cli.commands import resources

LINE = {
    "AccountNumber": 1000,
    "BaseAmountValue": 120,
    "Discount": 0,
    "Quantity": 1,
    "Unit": "hours",
}
INVOICE = {"ProductLines": [LINE], "ContactGuid": GUID, "FutureField": {"unicode": "Æble"}}
PURCHASE = {
    "PurchaseType": "cash",
    "Lines": [{"Amount": 125, "AccountNumber": 7320, "VatCode": "I25"}],
    "VoucherDate": "2026-09-20",
    "ContactGuid": GUID,
}
STAMP = "opaque / + = timestamp"
CASES = [
    ("invoices", "list", "GET", "/v1/456/invoices", None),
    ("invoices", "get", "GET", f"/v1/456/invoices/{GUID}", None),
    ("invoices", "create", "POST", "/v1/456/invoices", INVOICE),
    ("invoices", "update", "PUT", f"/v1.2/456/invoices/{GUID}", {**INVOICE, "Timestamp": STAMP}),
    ("invoices", "delete", "DELETE", f"/v1/456/invoices/{GUID}", {"Timestamp": STAMP}),
    (
        "invoices",
        "book",
        "POST",
        f"/v1/456/invoices/{GUID}/book",
        {"Timestamp": STAMP, "Number": 42},
    ),
    (
        "invoices",
        "send",
        "POST",
        f"/v1/456/invoices/{GUID}/email",
        {
            "Timestamp": STAMP,
            "ShouldAddTrustPilotEmailAsBcc": False,
            "Receiver": "fixture@example.test",
        },
    ),
    ("purchase-vouchers", "get", "GET", f"/v1/456/vouchers/purchase/{GUID}", None),
    ("purchase-vouchers", "create", "POST", "/v1.2/456/vouchers/purchase", PURCHASE),
    (
        "purchase-vouchers",
        "update",
        "PUT",
        f"/v1.1/456/vouchers/purchase/{GUID}",
        {**PURCHASE, "Timestamp": STAMP},
    ),
    (
        "purchase-vouchers",
        "delete",
        "DELETE",
        f"/v1/456/vouchers/purchase/{GUID}",
        {"Timestamp": STAMP},
    ),
    (
        "purchase-vouchers",
        "book",
        "POST",
        f"/v1/456/vouchers/purchase/{GUID}/book",
        {"Timestamp": STAMP},
    ),
]


def arguments(group, verb):
    return [
        group,
        verb,
        *([GUID] if verb not in ("list", "create") else []),
        "--organization",
        "456",
        "--json",
    ]


@pytest.mark.parametrize("group,verb,method,path,body", CASES)
@pytest.mark.parametrize("stdin", [False, True])
def test_exact_voucher_operation(wire, tmp_path, group, verb, method, path, body, stdin):
    runner, calls = wire
    args = arguments(group, verb)
    source = json.dumps(body)
    if body is not None:
        p = tmp_path / "voucher.json"
        p.write_text(source)
        args += ["--input", "-" if stdin else str(p)]
    result = runner.invoke(app, args, input=source if stdin and body is not None else None)
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {"Items": [{"Name": "Æble"}], "Next": "preserved"}
    assert len(calls) == 1 and calls[0].method == method and calls[0].url.path == path
    assert (json.loads(calls[0].content) if calls[0].content else None) == body


def test_invoice_query_mapping(wire):
    runner, calls = wire
    options = {
        "start-date": "2026-01-01",
        "end-date": "2026-09-20",
        "fields": "Guid,Timestamp",
        "free-text-search": "Æ & +",
        "status-filter": "Draft",
        "query-filter": "ContactName eq 'Æ'",
        "changes-since": "2026-09-01",
        "page": "2",
        "page-size": "1000",
        "sort": "VoucherDate",
        "sort-order": "ascending",
    }
    args = arguments("invoices", "list") + ["--no-deleted-only"]
    for k, v in options.items():
        args += ["--" + k, v]
    assert runner.invoke(app, args).exit_code == 0
    expected = {
        k.split("-")[0] + "".join(x.title() for x in k.split("-")[1:]): v
        for k, v in options.items()
    }
    assert dict(parse_qsl(calls[0].url.query.decode())) == {**expected, "deletedOnly": "false"}


@pytest.mark.parametrize("group", ["invoices", "purchase-vouchers"])
@pytest.mark.parametrize("verb", ["book", "delete"])
def test_timestamp_options_no_hidden_read(wire, group, verb):
    runner, calls = wire
    result = runner.invoke(app, arguments(group, verb) + ["--timestamp", STAMP])
    assert result.exit_code == 0 and len(calls) == 1
    assert json.loads(calls[0].content) == {"Timestamp": STAMP}


def test_send_options(wire):
    runner, calls = wire
    result = runner.invoke(
        app,
        arguments("invoices", "send")
        + [
            "--timestamp",
            STAMP,
            "--receiver",
            "fixture@example.test",
            "--subject",
            "Invoice",
            "--message",
            "Hello [link-to-pdf]",
            "--no-trustpilot-bcc",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(calls[0].content) == {
        "Timestamp": STAMP,
        "Receiver": "fixture@example.test",
        "Subject": "Invoice",
        "Message": "Hello [link-to-pdf]",
        "ShouldAddTrustPilotEmailAsBcc": False,
    }


@pytest.mark.parametrize(
    "group,verb,body,args",
    [
        ("invoices", "create", {}, []),
        ("invoices", "create", {"ProductLines": [{"Quantity": 1}]}, []),
        ("invoices", "update", INVOICE, []),
        ("purchase-vouchers", "update", PURCHASE, []),
        ("purchase-vouchers", "create", {"PurchaseType": "cash", "Lines": [{"Amount": "125"}]}, []),
        ("invoices", "book", {}, []),
        ("invoices", "book", {"Timestamp": STAMP}, ["--timestamp", STAMP]),
        ("invoices", "send", {}, []),
        (
            "invoices",
            "send",
            {},
            ["--trustpilot-bcc", "--no-trustpilot-bcc"],
        ),
        ("invoices", "list", None, ["--deleted-only", "--no-deleted-only"]),
        ("purchase-vouchers", "list", None, []),
    ],
)
def test_invalid_voucher_input_sends_nothing(wire, group, verb, body, args):
    runner, calls = wire
    cmd = arguments(group, verb) + args
    if body is not None:
        cmd += ["--input", "-"]
    result = runner.invoke(app, cmd, input=json.dumps(body) if body is not None else None)
    assert result.exit_code == 2 and not calls and not result.stdout


@pytest.mark.parametrize("group,verb,method,path,body", [x for x in CASES if x[2] != "GET"])
@pytest.mark.parametrize("failure", [409, "timeout"])
def test_financial_failure_never_retries(
    wire, monkeypatch, group, verb, method, path, body, failure
):
    runner, _ = wire
    calls = []

    class Auth:
        def credentials(self):
            from dinero_cli.auth import Credentials

            return Credentials("sentinel-secret", ("sentinel-secret",))

    def respond(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("sentinel-secret")
        return httpx.Response(409, json={"Message": "Timestamp outdated", "ErrorCode": 58})

    monkeypatch.setattr(
        resources,
        "APIClient",
        lambda settings: APIClient(settings, auth=Auth(), transport=httpx.MockTransport(respond)),
    )
    result = runner.invoke(app, arguments(group, verb) + ["--input", "-"], input=json.dumps(body))
    assert result.exit_code == (5 if failure == "timeout" else 4)
    assert not result.stdout and len(calls) == 1
    assert calls[0].method == method and calls[0].url.path == path
    assert json.loads(calls[0].content) == body
    error = json.loads(result.stderr)
    assert error["status"] == (None if failure == "timeout" else 409)
    assert "sentinel-secret" not in result.stderr


@pytest.mark.parametrize(
    "group,verb",
    [
        ("invoices", "create"),
        ("invoices", "update"),
        ("purchase-vouchers", "create"),
        ("purchase-vouchers", "update"),
    ],
)
def test_convenience_options_merge_with_nested_json(wire, group, verb):
    runner, calls = wire
    invoice = group == "invoices"
    body = {"ProductLines": [LINE]} if invoice else {"Lines": [{"Amount": 125}]}
    args = arguments(group, verb) + ["--input", "-", "--contact-guid", GUID]
    expected = {**body, "ContactGuid": GUID}
    if invoice:
        args += ["--date", "2026-09-20", "--description", "Consulting"]
        expected.update(Date="2026-09-20", Description="Consulting")
    else:
        args += [
            "--voucher-date",
            "2026-09-20",
            "--purchase-type",
            "cash",
            "--file-guid",
            "file-guid",
            "--deposit-account-number",
            "55000",
        ]
        expected.update(
            VoucherDate="2026-09-20",
            PurchaseType="cash",
            FileGuid="file-guid",
            DepositAccountNumber=55000,
        )
    if verb == "update":
        args += ["--timestamp", STAMP]
        expected["Timestamp"] = STAMP
    result = runner.invoke(app, args, input=json.dumps(body))
    assert result.exit_code == 0, result.stderr
    assert json.loads(calls[0].content) == expected
