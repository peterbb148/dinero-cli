"""Shared execution and explicit payload construction for dedicated resource commands."""

import asyncio
from typing import Annotated, Any
from uuid import UUID

import typer
from pydantic import BaseModel, ValidationError

from dinero_cli.client import APIClient
from dinero_cli.config import load_settings
from dinero_cli.errors import CLIError
from dinero_cli.output import emit
from dinero_cli.payloads import read_object

Input = Annotated[
    str | None, typer.Option("--input", help="UTF-8 JSON object file, or - for stdin.")
]
Organization = Annotated[str | None, typer.Option(help="Override the selected organization.")]
Guid = Annotated[UUID, typer.Argument(help="Resource GUID from a previous read.")]
Fields = Annotated[str | None, typer.Option(help="Comma-separated API response field names.")]
Page = Annotated[
    int | None, typer.Option(min=0, help="Zero-based page; only this page is fetched.")
]
PageSize = Annotated[int | None, typer.Option(min=1, max=1000, help="Items per page (1–1000).")]
QueryFilter = Annotated[str | None, typer.Option(help="Dinero queryFilter expression, unchanged.")]
ChangesSince = Annotated[str | None, typer.Option(help="Dinero changesSince date/time, unchanged.")]


def boolean(yes: bool, no: bool, field: str) -> bool | None:
    """Keep omitted boolean options distinct from explicit false; reject opposing flags."""
    if yes and no:
        raise CLIError(f"Conflicting boolean options for {field}.")
    return True if yes else False if no else None


def payload(
    input_file: str | None, options: dict[str, Any], model: type[BaseModel]
) -> dict[str, Any]:
    """Reject duplicate top-level fields, validate structure and retain the original JSON."""
    body = read_object(input_file) if input_file is not None else {}
    supplied = {key: value for key, value in options.items() if value is not None}
    if body.keys() & supplied.keys():
        raise CLIError("A payload field was supplied in both --input and an option.")
    body.update(supplied)
    try:
        model.model_validate(body)
    except ValidationError as error:
        raise CLIError(f"Payload does not satisfy {model.__name__}; see command help.") from error
    return body


def execute(
    method: str,
    path: str,
    organization: str | None,
    json_output: bool,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> None:
    """Send one dedicated operation using common authentication, errors and presentation."""
    settings = load_settings(organization=organization)
    pairs = [
        (key, str(value).lower() if isinstance(value, bool) else str(value))
        for key, value in (query or {}).items()
        if value is not None
    ]
    result = asyncio.run(APIClient(settings).request(method, path, query=pairs, body=body))
    emit(result, json_mode=json_output or settings.output == "json")
