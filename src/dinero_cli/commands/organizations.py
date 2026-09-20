"""Organization discovery without implicitly selecting an accounting context."""

import typer

from dinero_cli.commands.config import Json
from dinero_cli.commands.resources import Fields, execute

app = typer.Typer(no_args_is_help=True, help="Discover organizations accessible to your login.")


@app.command("list")
def list_organizations(fields: Fields = None, json_output: Json = False) -> None:
    """List accessible organizations; no default organization is required or saved."""
    execute("GET", "/v1/organizations", None, json_output, query={"fields": fields})
