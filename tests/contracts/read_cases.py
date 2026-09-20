"""Read-only command contracts with explicit option inventories."""

from dataclasses import replace

from resource_cases import BASE, contract

from devtools.contracts import Contract

OPTIONS = {
    ("entries", "list"): {"--from-date", "--to-date", "--include-primo", "--no-include-primo"},
    ("entries", "changes"): {
        "--changes-from",
        "--changes-to",
        "--include-primo",
        "--no-include-primo",
    },
    ("accounts", "entry"): {"--fields", "--category-filter"},
    ("accounts", "purchase"): {"--fields"},
    ("accounts", "deposit"): {"--fields"},
    ("accounting-years", "list"): set(),
    ("vat-types", "list"): set(),
    ("files", "list"): {
        "--extensions",
        "--uploaded-before",
        "--uploaded-after",
        "--file-status",
        "--page",
        "--page-size",
    },
}
CONTRACTS = {
    (name,): Contract(kind="group", options=frozenset(), reason="Read-only resource namespace.")
    for name in ("entries", "accounts", "accounting-years", "vat-types", "files")
}
for path, options in OPTIONS.items():
    CONTRACTS[path] = replace(contract("organizations", "list"), options=frozenset(BASE | options))
