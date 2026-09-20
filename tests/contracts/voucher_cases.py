"""Financial commands run only through offline fixtures during contract checks."""

import json
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from pathlib import Path

from resource_cases import BASE, GUID, LIST, contract

from devtools.contracts import Contract

LINE = {"AccountNumber": 1000, "BaseAmountValue": 120, "Discount": 0, "Quantity": 1}
PAYLOADS = {
    ("invoices", "create"): {"ProductLines": [LINE]},
    ("invoices", "update"): {"ProductLines": [LINE], "Timestamp": "stamp"},
    ("purchase-vouchers", "create"): {"PurchaseType": "cash"},
    ("purchase-vouchers", "update"): {
        "PurchaseType": "cash",
        "Timestamp": "stamp",
        "VoucherDate": "2026-09-20",
        "ContactGuid": GUID,
        "Lines": [{"Amount": 125}],
    },
}


@contextmanager
def with_body(setup, body):
    with setup():
        path = Path("contract-voucher.json")
        path.write_text(json.dumps(body))
        try:
            yield
        finally:
            path.unlink()


def voucher_contract(group, verb):
    base = contract("organizations", "list")
    args = (GUID,) if verb not in ("list", "create") else ()
    options = BASE.copy()
    body = PAYLOADS.get((group, verb), {})
    if verb == "list":
        options |= LIST | {
            "--start-date",
            "--end-date",
            "--free-text-search",
            "--status-filter",
            "--sort",
            "--sort-order",
        }
    elif verb != "get":
        options.add("--input")
        args += ("--input", "contract-voucher.json")
        if verb in ("update", "delete", "book", "send"):
            options.add("--timestamp")
        if verb in ("create", "update"):
            options |= (
                {"--contact-guid", "--date", "--description"}
                if group == "invoices"
                else {
                    "--contact-guid",
                    "--voucher-date",
                    "--purchase-type",
                    "--file-guid",
                    "--deposit-account-number",
                }
            )
        if verb == "book":
            options.add("--number")
            body = {"Timestamp": "stamp"}
        if verb == "send":
            options |= {
                "--receiver",
                "--subject",
                "--message",
                "--trustpilot-bcc",
                "--no-trustpilot-bcc",
            }
            body = {"ShouldAddTrustPilotEmailAsBcc": False}
    cases = []
    for case in base.cases:
        expected = case.expected
        if case.failure == "transport" and verb not in ("get", "list"):
            expected = {
                **expected,
                "message": (
                    "API transport failed. The write result is uncertain; "
                    "inspect server state before repeating it."
                ),
            }
        cases.append(
            replace(
                case,
                args=(*args, *case.args),
                expected=expected,
                setup=partial(with_body, case.setup, body),
            )
        )
    return replace(
        base,
        options=frozenset(options),
        cases=tuple(cases),
        reason="One explicit voucher operation; draft/book/send/delete never chain or retry.",
    )


CONTRACTS = {}
for group, verbs in [
    ("invoices", ["list", "get", "create", "update", "delete", "book", "send"]),
    ("purchase-vouchers", ["get", "create", "update", "delete", "book"]),
]:
    CONTRACTS[(group,)] = Contract(
        kind="group", options=frozenset(), reason="Explicit accounting resource operations."
    )
    for verb in verbs:
        CONTRACTS[(group, verb)] = voucher_contract(group, verb)
