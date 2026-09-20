"""Explicit HTTP escape hatch using the same services as dedicated resource commands."""

import asyncio
from typing import Annotated

import typer

from dinero_cli.client import APIClient
from dinero_cli.commands.config import Json
from dinero_cli.config import load_settings
from dinero_cli.errors import CLIError
from dinero_cli.output import emit
from dinero_cli.payloads import read_object

app = typer.Typer(
    no_args_is_help=True,
    help="Send one authenticated JSON API request. No redirects or automatic retries.",
)
APIPath = Annotated[
    str, typer.Argument(help="API-root-relative path; optionally include {organizationId}.")
]
Organization = Annotated[
    str | None, typer.Option(help="Override organization used only in {organizationId}.")
]
Query = Annotated[
    list[str] | None,
    typer.Option(
        "--query", help="Repeat KEY=VALUE; duplicates and order are preserved and encoded."
    ),
]
Input = Annotated[
    str | None,
    typer.Option("--input", help="UTF-8 JSON object file, or - for stdin. No multipart."),
]


def query_pairs(values: list[str] | None) -> list[tuple[str, str]]:
    """Split once, allowing empty values and repeated keys without interpreting API fields."""
    pairs = []
    for value in values or []:
        key, separator, item = value.partition("=")
        if not key or not separator:
            raise CLIError("Each --query must be KEY=VALUE with a nonempty key.")
        pairs.append((key, item))
    return pairs


def execute(
    method: str,
    path: str,
    organization: str | None,
    query: list[str] | None,
    input_file: str | None,
    json_output: bool,
) -> None:
    """Validate local input before asking the common client to authenticate and send once."""
    settings = load_settings(organization=organization)
    pairs = query_pairs(query)
    body = read_object(input_file) if input_file is not None else None
    result = asyncio.run(APIClient(settings).request(method, path, query=pairs, body=body))
    emit(result, json_mode=json_output or settings.output == "json")


@app.command()
def get(
    path: APIPath,
    organization: Organization = None,
    query: Query = None,
    json_output: Json = False,
) -> None:
    """Read an API resource; request bodies are not supported."""
    execute("GET", path, organization, query, None, json_output)


@app.command()
def post(
    path: APIPath,
    organization: Organization = None,
    query: Query = None,
    input_file: Input = None,
    json_output: Json = False,
) -> None:
    """Create or invoke an API operation. This can change accounting state."""
    execute("POST", path, organization, query, input_file, json_output)


@app.command()
def put(
    path: APIPath,
    organization: Organization = None,
    query: Query = None,
    input_file: Input = None,
    json_output: Json = False,
) -> None:
    """Update an API resource. This changes accounting state."""
    execute("PUT", path, organization, query, input_file, json_output)


@app.command()
def delete(
    path: APIPath,
    organization: Organization = None,
    query: Query = None,
    input_file: Input = None,
    json_output: Json = False,
) -> None:
    """Delete an API resource. Destructive; executes without an interactive confirmation."""
    execute("DELETE", path, organization, query, input_file, json_output)
