"""Distinct chart-of-accounts views preserve each endpoint's supported filters."""

from typing import Annotated

import typer

from dinero_cli.commands.config import Json
from dinero_cli.commands.resources import Fields, Organization, execute

app = typer.Typer(no_args_is_help=True, help="Read entry, purchase and deposit accounts.")


@app.command()
def entry(
    organization: Organization = None,
    fields: Fields = None,
    category_filter: Annotated[str | None, typer.Option(help="Exact Dinero category name.")] = None,
    json_output: Json = False,
) -> None:
    """Read the chart of accounts; select Category/VatCode through --fields when needed."""
    execute(
        "GET",
        "/v1/{organizationId}/accounts/entry",
        organization,
        json_output,
        query={"fields": fields, "categoryFilter": category_filter},
    )


@app.command()
def purchase(
    organization: Organization = None, fields: Fields = None, json_output: Json = False
) -> None:
    """Read purchase accounts and their API-defined VAT/category metadata."""
    execute(
        "GET",
        "/v1/{organizationId}/accounts/purchase",
        organization,
        json_output,
        query={"fields": fields},
    )


@app.command()
def deposit(
    organization: Organization = None, fields: Fields = None, json_output: Json = False
) -> None:
    """Read deposit accounts; use --fields for IsDefault/IsHidden when needed."""
    execute(
        "GET",
        "/v1/{organizationId}/accounts/deposit",
        organization,
        json_output,
        query={"fields": fields},
    )
