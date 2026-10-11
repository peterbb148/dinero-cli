"""Native resource smoke cases use only the private build fixture, never live accounting."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

GUID = "cdb485f3-a188-48b1-8d40-f6c8014c9f21"
STAMP = "opaque / + = timestamp"
DOCUMENT = b"%PDF-1.7\nfixture\x00\xff\n"
LOOKUP_VARIANTS = {
    "00000000-0000-0000-0000-000000000011": [],
    "00000000-0000-0000-0000-000000000012": [GUID, "00000000-0000-0000-0000-000000000013"],
}
NO_SIMILAR = {"SimilarFound": False, "SimilarGuid": None, "VoucherNumber": None}
DOWNLOAD_FAILURES = {
    "00000000-0000-0000-0000-000000000001": (4, 403),
    "00000000-0000-0000-0000-000000000002": (6, 429),
    "00000000-0000-0000-0000-000000000003": (5, None),
}
Case = tuple[list[str], str, str, dict[str, Any] | None]
Request = tuple[str, str, bytes, str | None]
Invoke = Callable[[list[str], int, str | None], Any]


def resource_cases() -> list[Case]:
    """Describe each dedicated API operation independently of the command implementation."""
    cases: list[Case] = [(["organizations", "list"], "GET", "/v1/organizations", None)]
    cases.extend(
        [
            (["files", "download", GUID], "GET", f"/v1/456/files/{GUID}", None),
            (
                ["purchase-vouchers", "get-by-file", GUID],
                "GET",
                f"/v1/456/vouchers/purchase/fileguid/{GUID}",
                None,
            ),
            (
                ["purchase-vouchers", "similar"],
                "POST",
                "/v1/456/vouchers/purchase/similar",
                {"PurchaseType": "cash", "Lines": [{"Amount": 125, "Description": "Æble"}]},
            ),
        ]
    )
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
            destination = Path(directory) / "native-receipt.bin"
            is_download = args[:2] == ["files", "download"]
            if is_download:
                args += ["--output", str(destination)]
            source = json.dumps(body, ensure_ascii=False) if body is not None else None
            if source is not None:
                file = Path(directory) / "native-voucher.json"
                file.write_text(source, encoding="utf-8")
                args += ["--input", str(file) if use_file else "-"]
            count = len(requests)
            value = invoke(args, 0, None if use_file else source)
            expected = None if method == "DELETE" else response
            if is_download:
                expected = {"path": str(destination), "bytes": len(DOCUMENT)}
                if not destination.is_file() or destination.read_bytes() != DOCUMENT:
                    raise ValueError("Native resource smoke failed: download bytes")
            elif args[:2] == ["purchase-vouchers", "get-by-file"]:
                expected = [GUID]
            elif args[:2] == ["purchase-vouchers", "similar"]:
                expected = {"SimilarFound": True, "SimilarGuid": GUID, "VoucherNumber": 17}
            if value != expected:
                raise ValueError("Native resource smoke failed: response fidelity")
            if len(requests) != count + 1:
                raise ValueError("Native resource smoke failed: hidden request or retry")
            actual_method, actual_path, raw, auth = requests[-1]
            if (actual_method, actual_path, auth) != (method, path, "Bearer " + token):
                raise ValueError("Native resource smoke failed: method, path or authorization")
            if (json.loads(raw) if raw else None) != body:
                raise ValueError("Native resource smoke failed: payload fidelity")
    # Empty and ambiguous lookup results must survive the packaged CLI unchanged.
    for guid, expected_guids in LOOKUP_VARIANTS.items():
        count = len(requests)
        value = invoke(["purchase-vouchers", "get-by-file", guid, "--organization", "456"], 0, None)
        if (
            value != expected_guids
            or len(requests) != count + 1
            or requests[-1]
            != (
                "GET",
                f"/v1/456/vouchers/purchase/fileguid/{guid}",
                b"",
                "Bearer " + token,
            )
        ):
            raise ValueError("Native resource smoke failed: draft lookup shapes")
    count = len(requests)
    no_similar_body = {"PurchaseType": "cash", "__smoke_no_similar": True}
    value = invoke(
        ["purchase-vouchers", "similar", "--organization", "456", "--input", "-"],
        0,
        json.dumps(no_similar_body),
    )
    if (
        value != NO_SIMILAR
        or len(requests) != count + 1
        or requests[-1][:2]
        != (
            "POST",
            "/v1/456/vouchers/purchase/similar",
        )
        or json.loads(requests[-1][2]) != no_similar_body
        or requests[-1][3] != "Bearer " + token
    ):
        raise ValueError("Native resource smoke failed: similar not found")
    # A second download cannot overwrite a file; failed responses cannot leave partial bytes.
    destination = Path(directory) / "native-receipt.bin"
    count = len(requests)
    error = invoke(
        ["files", "download", GUID, "--organization", "456", "--output", str(destination)], 2, None
    )
    if (
        len(requests) != count
        or error.get("error") is not True
        or destination.read_bytes() != DOCUMENT
    ):
        raise ValueError("Native resource smoke failed: download overwrite")
    for guid, (code, status) in DOWNLOAD_FAILURES.items():
        target = Path(directory) / f"failed-{guid}.bin"
        count = len(requests)
        error = invoke(
            ["files", "download", guid, "--organization", "456", "--output", str(target)],
            code,
            None,
        )
        if (
            len(requests) != count + 1
            or error.get("status") != status
            or error.get("error") is not True
        ):
            raise ValueError("Native resource smoke failed: download error or retry")
        if target.exists() or list(Path(directory).glob(".dinero-download-*")):
            raise ValueError("Native resource smoke failed: partial download")
        if code == 6 and error["details"].get("retry_after") != "17":
            raise ValueError("Native resource smoke failed: download rate limit")
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
