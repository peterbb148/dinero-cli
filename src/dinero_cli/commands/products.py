"""Dedicated products operations preserve the verified v1 API contract."""

from typing import Annotated

import typer

from dinero_cli.commands.config import Json
from dinero_cli.commands.resources import (
    ChangesSince,
    Fields,
    Guid,
    Input,
    Organization,
    Page,
    PageSize,
    QueryFilter,
    boolean,
    execute,
    payload,
)
from dinero_cli.resource_models import ProductBody

app = typer.Typer(no_args_is_help=True, help="Read and change products in Dinero.")


@app.command("list")
def list_products(
    organization: Organization = None,
    fields: Fields = None,
    query_filter: QueryFilter = None,
    changes_since: ChangesSince = None,
    deleted_only: Annotated[
        bool, typer.Option("--deleted-only", help="Send deletedOnly=true.")
    ] = False,
    no_deleted_only: Annotated[
        bool, typer.Option("--no-deleted-only", help="Send deletedOnly=false.")
    ] = False,
    page: Page = None,
    page_size: PageSize = None,
    free_text_search: Annotated[str | None, typer.Option(help="Dinero freeTextSearch.")] = None,
    json_output: Json = False,
) -> None:
    """Read one page; omitted query options keep Dinero's defaults."""
    execute(
        "GET",
        "/v1/{organizationId}/products",
        organization,
        json_output,
        query={
            "fields": fields,
            "queryFilter": query_filter,
            "changesSince": changes_since,
            "deletedOnly": boolean(deleted_only, no_deleted_only, "deletedOnly"),
            "page": page,
            "pageSize": page_size,
            "freeTextSearch": free_text_search,
        },
    )


@app.command()
def get(guid: Guid, organization: Organization = None, json_output: Json = False) -> None:
    """Read one resource by GUID."""
    execute("GET", f"/v1/{{organizationId}}/products/{guid}", organization, json_output)


@app.command()
def create(
    name: Annotated[str | None, typer.Option(help="Name field.")] = None,
    base_amount_value: Annotated[
        float | None, typer.Option(help="Required BaseAmountValue, excluding VAT.")
    ] = None,
    quantity: Annotated[
        float | None, typer.Option(help="Required Quantity; no implicit default.")
    ] = None,
    account_number: Annotated[int | None, typer.Option(help="Required AccountNumber.")] = None,
    unit: Annotated[str | None, typer.Option(help="Required Unit, e.g. hours or parts.")] = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Create a resource (mutation).

    Required JSON/options: BaseAmountValue, Quantity, AccountNumber, Unit.

    Supply all required fields explicitly, including false boolean flags. Remaining API fields
    can be supplied through --input FILE or --input -. Duplicate option/JSON fields are rejected.
    Updates never fetch or merge the existing resource automatically.
    """
    body = payload(
        input_file,
        {
            "Name": name,
            "BaseAmountValue": base_amount_value,
            "Quantity": quantity,
            "AccountNumber": account_number,
            "Unit": unit,
        },
        ProductBody,
    )
    execute("POST", "/v1/{organizationId}/products", organization, json_output, body=body)


@app.command()
def update(
    guid: Guid,
    name: Annotated[str | None, typer.Option(help="Name field.")] = None,
    base_amount_value: Annotated[
        float | None, typer.Option(help="Required BaseAmountValue, excluding VAT.")
    ] = None,
    quantity: Annotated[
        float | None, typer.Option(help="Required Quantity; no implicit default.")
    ] = None,
    account_number: Annotated[int | None, typer.Option(help="Required AccountNumber.")] = None,
    unit: Annotated[str | None, typer.Option(help="Required Unit, e.g. hours or parts.")] = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Update a resource (mutation).

    Required JSON/options: BaseAmountValue, Quantity, AccountNumber, Unit.

    Supply all required fields explicitly, including false boolean flags. Remaining API fields
    can be supplied through --input FILE or --input -. Duplicate option/JSON fields are rejected.
    Updates never fetch or merge the existing resource automatically.
    """
    body = payload(
        input_file,
        {
            "Name": name,
            "BaseAmountValue": base_amount_value,
            "Quantity": quantity,
            "AccountNumber": account_number,
            "Unit": unit,
        },
        ProductBody,
    )
    execute("PUT", f"/v1/{{organizationId}}/products/{guid}", organization, json_output, body=body)


@app.command()
def delete(guid: Guid, organization: Organization = None, json_output: Json = False) -> None:
    """Delete the resource. Destructive; no prompt, request body or automatic retry."""
    execute("DELETE", f"/v1/{{organizationId}}/products/{guid}", organization, json_output)
