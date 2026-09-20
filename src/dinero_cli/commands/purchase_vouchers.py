"""Dedicated purchase-vouchers commands keep drafts, booking and sending explicit."""

from typing import Annotated

import typer

from dinero_cli.commands.config import Json
from dinero_cli.commands.resources import (
    Guid,
    Input,
    Organization,
    execute,
    payload,
)
from dinero_cli.voucher_models import (
    BookModel,
    PurchaseVoucherCreateModelV2,
    PurchaseVoucherUpdateModel,
    TimestampObject,
)

app = typer.Typer(
    no_args_is_help=True, help="Read purchase-vouchers and explicitly change accounting state."
)
Timestamp = Annotated[
    str | None, typer.Option(help="Opaque Timestamp from a prior read; sent unchanged.")
]


@app.command()
def create(
    contact_guid: Annotated[
        str | None, typer.Option(help="ContactGuid field; omission keeps API behavior.")
    ] = None,
    voucher_date: Annotated[
        str | None, typer.Option(help="VoucherDate field; omission keeps API behavior.")
    ] = None,
    purchase_type: Annotated[
        str | None, typer.Option(help="PurchaseType field; omission keeps API behavior.")
    ] = None,
    file_guid: Annotated[
        str | None, typer.Option(help="FileGuid field; omission keeps API behavior.")
    ] = None,
    deposit_account_number: Annotated[
        int | None, typer.Option(help="DepositAccountNumber field; omission keeps API behavior.")
    ] = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Create a draft only. Does not book or send.

    Required JSON fields: PurchaseType.
    Use --input FILE or --input - for nested lines and other API fields.
    Explicit body options cannot duplicate fields from the input object.
    """
    body = payload(
        input_file,
        {
            "ContactGuid": contact_guid,
            "VoucherDate": voucher_date,
            "PurchaseType": purchase_type,
            "FileGuid": file_guid,
            "DepositAccountNumber": deposit_account_number,
        },
        PurchaseVoucherCreateModelV2,
    )
    execute(
        "POST", "/v1.2/{organizationId}/vouchers/purchase", organization, json_output, body=body
    )


@app.command()
def get(
    guid: Guid,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Read a voucher and its current Timestamp."""
    execute("GET", f"/v1/{{organizationId}}/vouchers/purchase/{guid}", organization, json_output)


@app.command()
def update(
    guid: Guid,
    timestamp: Timestamp = None,
    contact_guid: Annotated[
        str | None, typer.Option(help="ContactGuid field; omission keeps API behavior.")
    ] = None,
    voucher_date: Annotated[
        str | None, typer.Option(help="VoucherDate field; omission keeps API behavior.")
    ] = None,
    purchase_type: Annotated[
        str | None, typer.Option(help="PurchaseType field; omission keeps API behavior.")
    ] = None,
    file_guid: Annotated[
        str | None, typer.Option(help="FileGuid field; omission keeps API behavior.")
    ] = None,
    deposit_account_number: Annotated[
        int | None, typer.Option(help="DepositAccountNumber field; omission keeps API behavior.")
    ] = None,
    input_file: Input = None,
    organization: Organization = None,
    json_output: Json = False,
) -> None:
    """Update the supplied voucher. No hidden read/merge or Timestamp refresh.

    Required JSON fields: ContactGuid, Lines, PurchaseType, Timestamp, VoucherDate.
    Use --input FILE or --input - for nested lines and other API fields.
    Explicit body options cannot duplicate fields from the input object.
    """
    body = payload(
        input_file,
        {
            "Timestamp": timestamp,
            "ContactGuid": contact_guid,
            "VoucherDate": voucher_date,
            "PurchaseType": purchase_type,
            "FileGuid": file_guid,
            "DepositAccountNumber": deposit_account_number,
        },
        PurchaseVoucherUpdateModel,
    )
    execute(
        "PUT",
        f"/v1.1/{{organizationId}}/vouchers/purchase/{guid}",
        organization,
        json_output,
        body=body,
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
        "DELETE",
        f"/v1/{{organizationId}}/vouchers/purchase/{guid}",
        organization,
        json_output,
        body=body,
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
        "POST",
        f"/v1/{{organizationId}}/vouchers/purchase/{guid}/book",
        organization,
        json_output,
        body=body,
    )
