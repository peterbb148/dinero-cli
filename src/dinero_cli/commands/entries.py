"""Read accounting entries with only their documented date and primo filters."""

from datetime import datetime
from typing import Annotated

import typer

from dinero_cli.commands.config import Json
from dinero_cli.commands.resources import Organization, boolean, execute
from dinero_cli.errors import CLIError

app = typer.Typer(no_args_is_help=True, help="Read accounting entries and entry changes.")
DateTime = Annotated[str | None, typer.Option(help="ISO date or date/time; sent unchanged.")]
IncludePrimo = Annotated[bool, typer.Option("--include-primo", help="Send includePrimo=true.")]
NoIncludePrimo = Annotated[
    bool, typer.Option("--no-include-primo", help="Send includePrimo=false.")
]


def date_time(value: str | None) -> str | None:
    """Validate ISO date syntax without changing the selected date, time or timezone."""
    if value is not None:
        try:
            datetime.fromisoformat(value)
            if len(value) < 10 or value[4] != "-" or value[7] != "-":
                raise ValueError("Expected separated ISO date")
        except ValueError as error:
            raise CLIError("Dates must be ISO dates or date/times (YYYY-MM-DD...).") from error
    return value


@app.command("list")
def list_entries(
    organization: Organization = None,
    from_date: DateTime = None,
    to_date: DateTime = None,
    include_primo: IncludePrimo = False,
    no_include_primo: NoIncludePrimo = False,
    json_output: Json = False,
) -> None:
    """Read entries for the supplied period. No pagination or hidden date defaults."""
    execute(
        "GET",
        "/v1/{organizationId}/entries",
        organization,
        json_output,
        query={
            "fromDate": date_time(from_date),
            "toDate": date_time(to_date),
            "includePrimo": boolean(include_primo, no_include_primo, "includePrimo"),
        },
    )


@app.command()
def changes(
    organization: Organization = None,
    changes_from: DateTime = None,
    changes_to: DateTime = None,
    include_primo: IncludePrimo = False,
    no_include_primo: NoIncludePrimo = False,
    json_output: Json = False,
) -> None:
    """Read changes between changesFrom/changesTo; no automatic polling or pagination."""
    execute(
        "GET",
        "/v1/{organizationId}/entries/changes",
        organization,
        json_output,
        query={
            "changesFrom": date_time(changes_from),
            "changesTo": date_time(changes_to),
            "includePrimo": boolean(include_primo, no_include_primo, "includePrimo"),
        },
    )
