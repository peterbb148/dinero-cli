"""List document archive metadata; no binary download or upload is implied."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

import typer

from dinero_cli.commands.config import Json
from dinero_cli.commands.resources import Organization, Page, PageSize, execute
from dinero_cli.errors import CLIError

app = typer.Typer(no_args_is_help=True, help="Read metadata for files in the document archive.")


class FileStatus(StrEnum):
    """The public API's documented status values."""

    all = "All"
    used = "Used"
    unused = "Unused"


def upload_date(value: str | None) -> str | None:
    """Validate the file endpoint's YYYY/MM/DD dates and send them unchanged."""
    if value is not None:
        try:
            parsed = datetime.strptime(value, "%Y/%m/%d")
            if parsed.strftime("%Y/%m/%d") != value:
                raise ValueError("Expected exact date format")
        except ValueError as error:
            raise CLIError("Upload dates must use YYYY/MM/DD.") from error
    return value


@app.command("list")
def list_files(
    organization: Organization = None,
    extensions: Annotated[str | None, typer.Option(help="Comma-separated file extensions.")] = None,
    uploaded_before: Annotated[
        str | None, typer.Option(help="API uploadedBefore (YYYY/MM/DD).")
    ] = None,
    uploaded_after: Annotated[
        str | None, typer.Option(help="API uploadedAfter (YYYY/MM/DD).")
    ] = None,
    file_status: Annotated[FileStatus | None, typer.Option(help="All, Used or Unused.")] = None,
    page: Page = None,
    page_size: PageSize = None,
    json_output: Json = False,
) -> None:
    """Read one page of file metadata. Unused files are not necessarily separate expenses."""
    execute(
        "GET",
        "/v1/{organizationId}/files",
        organization,
        json_output,
        query={
            "extensions": extensions,
            "uploadedBefore": upload_date(uploaded_before),
            "uploadedAfter": upload_date(uploaded_after),
            "fileStatus": file_status.value if file_status is not None else None,
            "page": page,
            "pageSize": page_size,
        },
    )
