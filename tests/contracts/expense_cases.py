"""Offline document download, draft lookup and similar-purchase contracts."""

import json
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from pathlib import Path

from resource_cases import BASE, GUID, contract, setup

from devtools.contracts import Case


@contextmanager
def files_context(base, body=False):
    with base():
        if body:
            Path("similar.json").write_text(json.dumps({"PurchaseType": "cash"}), encoding="utf-8")
        try:
            yield
        finally:
            Path("receipt.bin").unlink(missing_ok=True)
            Path("similar.json").unlink(missing_ok=True)


base = contract("organizations", "list")
failures = tuple(case for case in base.cases if case.exit_code)
found = {"SimilarFound": True, "SimilarGuid": GUID, "VoucherNumber": 17}
missing = {"SimilarFound": False, "SimilarGuid": None, "VoucherNumber": None}

CONTRACTS = {
    ("purchase-vouchers", "get-by-file"): replace(
        base,
        options=frozenset(BASE),
        reason="Read all draft GUIDs linked to an explicit file without selecting one.",
        cases=tuple(
            Case((GUID,), expected=value, human=human, setup=partial(setup, value=value))
            for value, human in (([], ("No results",)), ([GUID], (GUID,)), ([GUID, GUID], (GUID,)))
        )
        + tuple(replace(case, args=(GUID, *case.args)) for case in failures),
    ),
    ("purchase-vouchers", "similar"): replace(
        base,
        options=frozenset(BASE | {"--input"}),
        reason="Read a similarity result with an explicit JSON body; no accounting mutation.",
        cases=tuple(
            replace(
                case,
                args=("--input", "similar.json", *case.args),
                setup=partial(files_context, case.setup, body=True),
                expected=(
                    {
                        **case.expected,
                        "message": (
                            "API transport failed. The write result is uncertain; "
                            "inspect server state before repeating it."
                        ),
                    }
                    if case.failure == "transport"
                    else case.expected
                ),
            )
            for case in (
                Case(
                    (),
                    expected=found,
                    human=("SimilarFound", "Yes", GUID),
                    setup=partial(setup, value=found),
                ),
                Case(
                    (),
                    expected=missing,
                    human=("SimilarFound", "No"),
                    setup=partial(setup, value=missing),
                ),
                *failures,
            )
        ),
    ),
    ("files", "download"): replace(
        base,
        options=frozenset(BASE | {"--output"}),
        reason="Save original document bytes; return documented local path and byte count.",
        cases=tuple(
            replace(
                case,
                args=(GUID, "--output", "receipt.bin", *case.args),
                setup=partial(files_context, case.setup),
            )
            for case in (
                Case(
                    (),
                    expected={"path": "receipt.bin", "bytes": 6},
                    human=("receipt.bin", "6"),
                    setup=partial(setup, value=b"\x00\xffdata"),
                ),
                Case(
                    (),
                    expected={"path": "receipt.bin", "bytes": 0},
                    human=("receipt.bin", "0"),
                    setup=setup,
                ),
                *failures,
            )
        ),
    ),
}
