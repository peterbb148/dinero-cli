"""Dedicated contacts operations preserve the verified v1 API contract."""

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
from dinero_cli.resource_models import ContactBody

app = typer.Typer(no_args_is_help=True, help="Read and change contacts in Dinero.")


@app.command("list")
def list_contacts(
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
    json_output: Json = False,
) -> None:
    """Read one page; omitted query options keep Dinero's defaults."""
    execute(
        "GET",
        "/v1/{organizationId}/contacts",
        organization,
        json_output,
        query={
            "fields": fields,
            "queryFilter": query_filter,
            "changesSince": changes_since,
            "deletedOnly": boolean(deleted_only, no_deleted_only, "deletedOnly"),
            "page": page,
            "pageSize": page_size,
        },
    )


@app.command()
def get(guid: Guid, organization: Organization = None, json_output: Json = False) -> None:
    """Read one resource by GUID."""
    execute("GET", f"/v1/{{organizationId}}/contacts/{guid}", organization, json_output)


@app.command()
def create(
    name: Annotated[str | None, typer.Option(help="Name field.")] = None,
    email: Annotated[str | None, typer.Option(help="Email field.")] = None,
    country_key: Annotated[str | None, typer.Option(help="Required CountryKey.")] = None,
    is_person: Annotated[
        bool, typer.Option("--is-person", help="Explicit true is_person.")
    ] = False,
    no_is_person: Annotated[
        bool, typer.Option("--no-is-person", help="Explicit false is_person.")
    ] = False,
    is_member: Annotated[
        bool, typer.Option("--is-member", help="Explicit true is_member.")
    ] = False,
    no_is_member: Annotated[
        bool, typer.Option("--no-is-member", help="Explicit false is_member.")
    ] = False,
    use_cvr: Annotated[bool, typer.Option("--use-cvr", help="Explicit true use_cvr.")] = False,
    no_use_cvr: Annotated[
        bool, typer.Option("--no-use-cvr", help="Explicit false use_cvr.")
    ] = False,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Create a resource (mutation).

    Required JSON/options: Name, CountryKey, IsPerson, IsMember, UseCvr.

    Supply all required fields explicitly, including false boolean flags. Remaining API fields
    can be supplied through --input FILE or --input -. Duplicate option/JSON fields are rejected.
    Updates never fetch or merge the existing resource automatically.
    """
    body = payload(
        input_file,
        {
            "Name": name,
            "Email": email,
            "CountryKey": country_key,
            "IsPerson": boolean(is_person, no_is_person, "IsPerson"),
            "IsMember": boolean(is_member, no_is_member, "IsMember"),
            "UseCvr": boolean(use_cvr, no_use_cvr, "UseCvr"),
        },
        ContactBody,
    )
    execute("POST", "/v1/{organizationId}/contacts", organization, json_output, body=body)


@app.command()
def update(
    guid: Guid,
    name: Annotated[str | None, typer.Option(help="Name field.")] = None,
    email: Annotated[str | None, typer.Option(help="Email field.")] = None,
    country_key: Annotated[str | None, typer.Option(help="Required CountryKey.")] = None,
    is_person: Annotated[
        bool, typer.Option("--is-person", help="Explicit true is_person.")
    ] = False,
    no_is_person: Annotated[
        bool, typer.Option("--no-is-person", help="Explicit false is_person.")
    ] = False,
    is_member: Annotated[
        bool, typer.Option("--is-member", help="Explicit true is_member.")
    ] = False,
    no_is_member: Annotated[
        bool, typer.Option("--no-is-member", help="Explicit false is_member.")
    ] = False,
    use_cvr: Annotated[bool, typer.Option("--use-cvr", help="Explicit true use_cvr.")] = False,
    no_use_cvr: Annotated[
        bool, typer.Option("--no-use-cvr", help="Explicit false use_cvr.")
    ] = False,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Update a resource (mutation).

    Required JSON/options: Name, CountryKey, IsPerson, IsMember, UseCvr.

    Supply all required fields explicitly, including false boolean flags. Remaining API fields
    can be supplied through --input FILE or --input -. Duplicate option/JSON fields are rejected.
    Updates never fetch or merge the existing resource automatically.
    """
    body = payload(
        input_file,
        {
            "Name": name,
            "Email": email,
            "CountryKey": country_key,
            "IsPerson": boolean(is_person, no_is_person, "IsPerson"),
            "IsMember": boolean(is_member, no_is_member, "IsMember"),
            "UseCvr": boolean(use_cvr, no_use_cvr, "UseCvr"),
        },
        ContactBody,
    )
    execute("PUT", f"/v1/{{organizationId}}/contacts/{guid}", organization, json_output, body=body)


@app.command()
def delete(guid: Guid, organization: Organization = None, json_output: Json = False) -> None:
    """Delete the resource. Destructive; no prompt, request body or automatic retry."""
    execute("DELETE", f"/v1/{{organizationId}}/contacts/{guid}", organization, json_output)
