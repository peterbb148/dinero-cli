"""Native resource smoke cases use only the private build fixture, never live accounting."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

GUID = "cdb485f3-a188-48b1-8d40-f6c8014c9f21"
STAMP = "opaque / + = timestamp"
Case = tuple[list[str], str, str, dict[str, Any] | None]
Request = tuple[str, str, bytes, str | None]
Invoke = Callable[[list[str], int, str | None], Any]


def resource_cases() -> list[Case]:
    """Describe each dedicated API operation independently of the command implementation."""
    cases: list[Case] = [(["organizations", "list"], "GET", "/v1/organizations", None)]
    for group, endpoint in (
        ("entries", "entries"),
        ("accounting-years", "accountingyears"),
        ("vat-types", "vatTypes"),
        ("files", "files"),
    ):
        cases.append(([group, "list"], "GET", f"/v1/456/{endpoint}", None))
    cases.append((["entries", "changes"], "GET", "/v1/456/entries/changes", None))
    for view in ("entry", "purchase", "deposit"):
        cases.append((["accounts", view], "GET", f"/v1/456/accounts/{view}", None))
    bodies: dict[str, dict[str, Any]] = {
        "contacts": {
            "Name": "Æble",
            "CountryKey": "DK",
            "IsPerson": False,
            "IsMember": False,
            "UseCvr": False,
        },
        "products": {
            "Name": "Æble",
            "BaseAmountValue": 120,
            "Quantity": 1,
            "AccountNumber": 1000,
            "Unit": "hours",
        },
        "invoices": {
            "ProductLines": [
                {
                    "Description": "Æble",
                    "AccountNumber": 1000,
                    "BaseAmountValue": 120,
                    "Discount": 0,
                    "Quantity": 1,
                }
            ]
        },
        "purchase-vouchers": {
            "PurchaseType": "cash",
            "ContactGuid": GUID,
            "VoucherDate": "2026-09-20",
            "Lines": [{"Amount": 125, "Description": "Æble"}],
        },
    }
    for group, body in bodies.items():
        endpoint = "vouchers/purchase" if group == "purchase-vouchers" else group
        base = f"/v1/456/{endpoint}"
        if group != "purchase-vouchers":
            cases.append(
                (
                    [group, "list", "--page", "0", "--page-size", "1"],
                    "GET",
                    base + "?page=0&pageSize=1",
                    None,
                )
            )
        cases.append(([group, "get", GUID], "GET", f"{base}/{GUID}", None))
        create_path = base.replace("/v1/", "/v1.2/") if group == "purchase-vouchers" else base
        cases.append(([group, "create"], "POST", create_path, body))
        update_path = f"{base}/{GUID}"
        update_body = body
        if group in ("invoices", "purchase-vouchers"):
            update_body = {**body, "Timestamp": STAMP}
            update_path = update_path.replace("/v1/", "/v1.2/" if group == "invoices" else "/v1.1/")
        cases.append(([group, "update", GUID], "PUT", update_path, update_body))
        delete_body = {"Timestamp": STAMP} if group in ("invoices", "purchase-vouchers") else None
        cases.append(([group, "delete", GUID], "DELETE", f"{base}/{GUID}", delete_body))
        if group in ("invoices", "purchase-vouchers"):
            cases.append(
                ([group, "book", GUID], "POST", f"{base}/{GUID}/book", {"Timestamp": STAMP})
            )
        if group == "invoices":
            cases.append(
                (
                    [group, "send", GUID],
                    "POST",
                    f"{base}/{GUID}/email",
                    {
                        "Timestamp": STAMP,
                        "ShouldAddTrustPilotEmailAsBcc": False,
                        "Receiver": "fixture@example.test",
                        "Message": "Æble",
                    },
                )
            )
    return cases


def verify_resources(
    invoke: Invoke, directory: str, requests: list[Request], token: str, response: Any
) -> int:
    """Require exact wire data and single requests from every packaged resource operation."""
    initial = len(requests)
    for arguments, method, path, body in resource_cases():
        for use_file in (False, True) if body is not None else (False,):
            args = arguments.copy()
            if args[0] != "organizations":
                args += ["--organization", "456"]
            source = json.dumps(body, ensure_ascii=False) if body is not None else None
            if source is not None:
                file = Path(directory) / "native-voucher.json"
                file.write_text(source, encoding="utf-8")
                args += ["--input", str(file) if use_file else "-"]
            count = len(requests)
            value = invoke(args, 0, None if use_file else source)
            if value != (None if method == "DELETE" else response):
                raise ValueError("Native resource smoke failed: response fidelity")
            if len(requests) != count + 1:
                raise ValueError("Native resource smoke failed: hidden request or retry")
            actual_method, actual_path, raw, auth = requests[-1]
            if (actual_method, actual_path, auth) != (method, path, "Bearer " + token):
                raise ValueError("Native resource smoke failed: method, path or authorization")
            if (json.loads(raw) if raw else None) != body:
                raise ValueError("Native resource smoke failed: payload fidelity")
    # Unknown body fields are preserved, so the private fixture can inject failure outcomes
    # without adding a production test mode or token endpoint override to the executable.
    for arguments, _, _, body in resource_cases():
        if arguments[0] != "invoices" or arguments[1] not in ("create", "book", "send", "delete"):
            continue
        for scenario, code, status in (
            ("conflict", 4, 409),
            ("rate", 6, 429),
            ("disconnect", 5, None),
        ):
            count = len(requests)
            source = json.dumps({**(body or {}), "__smoke_failure": scenario}, ensure_ascii=False)
            error = invoke([*arguments, "--organization", "456", "--input", "-"], code, source)
            if (
                len(requests) != count + 1
                or error.get("status") != status
                or error.get("error") is not True
            ):
                raise ValueError("Native resource smoke failed: mutation error or replay")
            if scenario == "disconnect" and "uncertain" not in error["message"]:
                raise ValueError("Native resource smoke failed: uncertain write diagnostic")
            if scenario == "rate" and error["details"].get("retry_after") != "17":
                raise ValueError("Native resource smoke failed: rate limit detail")
    count = len(requests)
    if invoke(["config", "get", "organization"], 0, None) != {"organization": "123"}:
        raise ValueError("Native resource smoke failed: organization override persisted")
    if not invoke(["auth", "status"], 0, None)["authorized"] or len(requests) != count:
        raise ValueError("Native resource smoke failed: local auth status")
    return len(requests) - initial
