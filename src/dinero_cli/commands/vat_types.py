"""Read VAT types using the documented organization endpoint."""

import typer

from dinero_cli.commands.config import Json
from dinero_cli.commands.resources import Organization, execute

app = typer.Typer(no_args_is_help=True, help="Read VAT types.")


@app.command("list")
def list_items(organization: Organization = None, json_output: Json = False) -> None:
    """Read VAT types; no pagination or additional query filters are supported."""
    execute("GET", "/v1/{organizationId}/vatTypes", organization, json_output)
