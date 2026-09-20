"""Dedicated invoices commands keep drafts, booking and sending explicit."""

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
from dinero_cli.voucher_models import (
    ApiMailoutModel,
    BookModel,
    InvoiceCreateModel,
    InvoiceUpdateModel,
    TimestampObject,
)

app = typer.Typer(
    no_args_is_help=True, help="Read invoices and explicitly change accounting state."
)
Timestamp = Annotated[
    str | None, typer.Option(help="Opaque Timestamp from a prior read; sent unchanged.")
]


@app.command("list")
def list_invoices(
    start_date: Annotated[
        str | None, typer.Option(help="Dinero startDate; sent unchanged.")
    ] = None,
    end_date: Annotated[str | None, typer.Option(help="Dinero endDate; sent unchanged.")] = None,
    fields: Fields = None,
    free_text_search: Annotated[
        str | None, typer.Option(help="Dinero freeTextSearch; sent unchanged.")
    ] = None,
    status_filter: Annotated[
        str | None, typer.Option(help="Dinero statusFilter; sent unchanged.")
    ] = None,
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
    sort: Annotated[str | None, typer.Option(help="Dinero sort; sent unchanged.")] = None,
    sort_order: Annotated[
        str | None, typer.Option(help="Dinero sortOrder; sent unchanged.")
    ] = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Read one page of invoices; no hidden pagination or date defaults."""
    execute(
        "GET",
        "/v1/{organizationId}/invoices",
        organization,
        json_output,
        query={
            "startDate": start_date,
            "endDate": end_date,
            "fields": fields,
            "freeTextSearch": free_text_search,
            "statusFilter": status_filter,
            "queryFilter": query_filter,
            "changesSince": changes_since,
            "deletedOnly": boolean(deleted_only, no_deleted_only, "deletedOnly"),
            "page": page,
            "pageSize": page_size,
            "sort": sort,
            "sortOrder": sort_order,
        },
    )


@app.command()
def get(
    guid: Guid,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Read a voucher and its current Timestamp."""
    execute("GET", f"/v1/{{organizationId}}/invoices/{guid}", organization, json_output)


@app.command()
def create(
    contact_guid: Annotated[
        str | None, typer.Option(help="ContactGuid field; omission keeps API behavior.")
    ] = None,
    date: Annotated[
        str | None, typer.Option(help="Date field; omission keeps API behavior.")
    ] = None,
    description: Annotated[
        str | None, typer.Option(help="Description field; omission keeps API behavior.")
    ] = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Create a draft only. Does not book or send.

    Required JSON fields: ProductLines.
    Use --input FILE or --input - for nested lines and other API fields.
    Explicit body options cannot duplicate fields from the input object.
    """
    body = payload(
        input_file,
        {"ContactGuid": contact_guid, "Date": date, "Description": description},
        InvoiceCreateModel,
    )
    execute("POST", "/v1/{organizationId}/invoices", organization, json_output, body=body)


@app.command()
def update(
    guid: Guid,
    timestamp: Timestamp = None,
    contact_guid: Annotated[
        str | None, typer.Option(help="ContactGuid field; omission keeps API behavior.")
    ] = None,
    date: Annotated[
        str | None, typer.Option(help="Date field; omission keeps API behavior.")
    ] = None,
    description: Annotated[
        str | None, typer.Option(help="Description field; omission keeps API behavior.")
    ] = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Update the supplied voucher. No hidden read/merge or Timestamp refresh.

    Required JSON fields: ProductLines, Timestamp.
    Use --input FILE or --input - for nested lines and other API fields.
    Explicit body options cannot duplicate fields from the input object.
    """
    body = payload(
        input_file,
        {
            "Timestamp": timestamp,
            "ContactGuid": contact_guid,
            "Date": date,
            "Description": description,
        },
        InvoiceUpdateModel,
    )
    execute(
        "PUT", f"/v1.2/{{organizationId}}/invoices/{guid}", organization, json_output, body=body
    )


@app.command()
def delete(
    guid: Guid,
    timestamp: Timestamp = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Delete the voucher (destructive). No prompt, automatic retry or Timestamp refresh.

    Required JSON fields: none (Timestamp can be supplied explicitly).
    Use --input FILE or --input - for nested lines and other API fields.
    Explicit body options cannot duplicate fields from the input object.
    """
    body = payload(input_file, {"Timestamp": timestamp}, TimestampObject)
    execute(
        "DELETE", f"/v1/{{organizationId}}/invoices/{guid}", organization, json_output, body=body
    )


@app.command()
def book(
    guid: Guid,
    timestamp: Timestamp = None,
    number: Annotated[
        int | None, typer.Option(help="Number field; omission keeps API behavior.")
    ] = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Book the voucher into the accounts. Financial mutation; no retry or automatic send.

    Required JSON fields: Timestamp.
    Use --input FILE or --input - for nested lines and other API fields.
    Explicit body options cannot duplicate fields from the input object.
    """
    body = payload(input_file, {"Timestamp": timestamp, "Number": number}, BookModel)
    execute(
        "POST", f"/v1/{{organizationId}}/invoices/{guid}/book", organization, json_output, body=body
    )


@app.command()
def send(
    guid: Guid,
    timestamp: Timestamp = None,
    receiver: Annotated[
        str | None, typer.Option(help="Receiver field; omission keeps API behavior.")
    ] = None,
    subject: Annotated[
        str | None, typer.Option(help="Subject field; omission keeps API behavior.")
    ] = None,
    message: Annotated[
        str | None, typer.Option(help="Message field; omission keeps API behavior.")
    ] = None,
    should_add_trust_pilot_email_as_bcc: Annotated[
        bool,
        typer.Option("--trustpilot-bcc", help="Explicitly enable TrustPilot BCC."),
    ] = False,
    no_should_add_trust_pilot_email_as_bcc: Annotated[
        bool,
        typer.Option("--no-trustpilot-bcc", help="Explicitly disable TrustPilot BCC."),
    ] = False,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Send the invoice by email. External delivery; no automatic booking or retry.

    Required JSON fields: ShouldAddTrustPilotEmailAsBcc.
    Use --input FILE or --input - for nested lines and other API fields.
    Explicit body options cannot duplicate fields from the input object.
    """
    body = payload(
        input_file,
        {
            "Timestamp": timestamp,
            "Receiver": receiver,
            "Subject": subject,
            "Message": message,
            "ShouldAddTrustPilotEmailAsBcc": boolean(
                should_add_trust_pilot_email_as_bcc,
                no_should_add_trust_pilot_email_as_bcc,
                "ShouldAddTrustPilotEmailAsBcc",
            ),
        },
        ApiMailoutModel,
    )
    execute(
        "POST",
        f"/v1/{{organizationId}}/invoices/{guid}/email",
        organization,
        json_output,
        body=body,
    )
