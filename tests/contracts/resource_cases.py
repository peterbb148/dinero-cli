"""Dedicated resources exercise common human/JSON output and all failure classes."""

from functools import partial

from api_cases import configured
from config_cases import error

from devtools.contracts import Case, Contract
from dinero_cli.commands import resources

GUID = "cdb485f3-a188-48b1-8d40-f6c8014c9f21"
CONTACT = (
    "--name",
    "Æble",
    "--country-key",
    "DK",
    "--no-is-person",
    "--no-is-member",
    "--no-use-cvr",
)
PRODUCT = (
    "--base-amount-value",
    "20.5",
    "--quantity",
    "2",
    "--account-number",
    "1000",
    "--unit",
    "hours",
)
BASE = {"--organization", "--json"}
LIST = {
    "--fields",
    "--query-filter",
    "--changes-since",
    "--deleted-only",
    "--no-deleted-only",
    "--page",
    "--page-size",
}
CONTACT_OPTIONS = {
    "--name",
    "--email",
    "--country-key",
    "--is-person",
    "--no-is-person",
    "--is-member",
    "--no-is-member",
    "--use-cvr",
    "--no-use-cvr",
    "--input",
}
PRODUCT_OPTIONS = {
    "--name",
    "--base-amount-value",
    "--quantity",
    "--account-number",
    "--unit",
    "--input",
}
setup = partial(configured, module=resources)


def contract(resource, verb):
    args = (GUID,) if verb in ("get", "update", "delete") else ()
    options = BASE.copy()
    if resource == "organizations":
        options = {"--json", "--fields"}
    elif verb == "list":
        options |= LIST
        if resource == "products":
            options.add("--free-text-search")
    elif verb in ("create", "update"):
        args += CONTACT if resource == "contacts" else PRODUCT
        options |= CONTACT_OPTIONS if resource == "contacts" else PRODUCT_OPTIONS
    transport = "API transport failed."
    if verb in ("create", "update", "delete"):
        transport += " The write result is uncertain; inspect server state before repeating it."
    missing = "Authorization is missing or its context changed; run auth login."
    invalid = "Invalid arguments. Use --help for command syntax."
    return Contract(
        kind="data",
        options=frozenset(options),
        reason="One dedicated resource operation through shared authenticated HTTP.",
        cases=(
            Case(
                args,
                expected={"Name": "Æble"},
                human=("Name", "Æble"),
                setup=partial(setup, value={"Name": "Æble"}),
            ),
            Case(args, expected=[], human=("No results",), setup=partial(setup, value=[])),
            Case(args, expected=None, human=("Completed",), setup=setup),
            Case(
                (*args, "--unknown"),
                expected=error(invalid),
                human=("Invalid arguments",),
                exit_code=2,
                failure="validation",
                setup=setup,
            ),
            Case(
                args,
                expected=error(missing),
                human=(missing,),
                exit_code=3,
                failure="authentication",
                setup=partial(setup, authorized=False),
            ),
            Case(
                args,
                expected={
                    "error": True,
                    "status": 400,
                    "message": "Rejected",
                    "details": {"response": {"Message": "Rejected"}},
                },
                human=("HTTP 400", "Rejected"),
                exit_code=4,
                failure="api",
                setup=partial(setup, status=400, value={"Message": "Rejected"}),
            ),
            Case(
                args,
                expected=error(transport),
                human=("API transport failed",),
                exit_code=5,
                failure="transport",
                setup=partial(setup, transport_error=True),
            ),
        ),
    )


CONTRACTS = {
    (resource,): Contract(
        kind="group", options=frozenset(), reason="Dedicated API resource namespace."
    )
    for resource in ("organizations", "contacts", "products")
}
CONTRACTS[("organizations", "list")] = contract("organizations", "list")
for resource in ("contacts", "products"):
    for verb in ("list", "get", "create", "update", "delete"):
        CONTRACTS[(resource, verb)] = contract(resource, verb)
