"""Verified invoice and purchase payload structures; accounting rules remain in Dinero."""

from pydantic import BaseModel, ConfigDict, Field


class InvoiceLinesCreateModel(BaseModel):
    """Structural fields from Dinero InvoiceLinesCreateModel."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    BaseAmountValue: float
    ProductGuid: str | None = Field(default=None)
    Description: str | None = Field(default=None)
    Comments: str | None = Field(default=None)
    Quantity: float
    AccountNumber: int
    Unit: str | None = Field(default=None)
    Discount: float
    LineType: str | None = Field(default=None)


class PurchaseVoucherLineCreateModel(BaseModel):
    """Structural fields from Dinero PurchaseVoucherLineCreateModel."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    AccountNumber: int | None = Field(default=None)
    Description: str | None = Field(default=None)
    Amount: float
    VatCode: str | None = Field(default=None)
    AccountTagName: str | None = Field(default=None)
    SynonymWithMostWeight: str | None = Field(default=None)
    TagId: str | None = Field(default=None)
    TagVersion: int | None = Field(default=None)


class InvoiceCreateModel(BaseModel):
    """Structural fields from Dinero InvoiceCreateModel."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    PaymentConditionNumberOfDays: int | None = Field(default=None)
    PaymentConditionType: str | None = Field(default=None)
    ReminderFee: float | None = Field(default=None)
    ReminderInterestRate: float | None = Field(default=None)
    IsMobilePayInvoiceEnabled: bool | None = Field(default=None)
    IsPensoPayEnabled: bool | None = Field(default=None)
    ContactGuid: str | None = Field(default=None)
    Guid: str | None = Field(default=None)
    ShowLinesInclVat: bool | None = Field(default=None)
    InvoiceTemplateId: str | None = Field(default=None)
    Currency: str | None = Field(default=None)
    Language: str | None = Field(default=None)
    ExternalReference: str | None = Field(default=None, min_length=0, max_length=128)
    Description: str | None = Field(default=None)
    Comment: str | None = Field(default=None)
    Date: str | None = Field(default=None)
    ProductLines: list[InvoiceLinesCreateModel]
    Address: str | None = Field(default=None)


class InvoiceUpdateModel(BaseModel):
    """Structural fields from Dinero InvoiceUpdateModel."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    Timestamp: str = Field(min_length=1)
    PaymentConditionNumberOfDays: int | None = Field(default=None)
    PaymentConditionType: str | None = Field(default=None)
    ReminderFee: float | None = Field(default=None)
    ReminderInterestRate: float | None = Field(default=None)
    IsMobilePayInvoiceEnabled: bool | None = Field(default=None)
    IsPensoPayEnabled: bool | None = Field(default=None)
    ContactGuid: str | None = Field(default=None)
    Guid: str | None = Field(default=None)
    ShowLinesInclVat: bool | None = Field(default=None)
    InvoiceTemplateId: str | None = Field(default=None)
    Currency: str | None = Field(default=None)
    Language: str | None = Field(default=None)
    ExternalReference: str | None = Field(default=None, min_length=0, max_length=128)
    Description: str | None = Field(default=None)
    Comment: str | None = Field(default=None)
    Date: str | None = Field(default=None)
    ProductLines: list[InvoiceLinesCreateModel]
    Address: str | None = Field(default=None)


class PurchaseVoucherCreateModelV2(BaseModel):
    """Structural fields from Dinero PurchaseVoucherCreateModelV2."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    Lines: list[PurchaseVoucherLineCreateModel] | None = Field(default=None)
    VoucherDate: str | None = Field(default=None)
    DepositAccountNumber: int | None = Field(default=None)
    RegionKey: str | None = Field(default=None)
    FileGuid: str | None = Field(default=None)
    ContactGuid: str | None = Field(default=None)
    PaymentDate: str | None = Field(default=None)
    PurchaseType: str = Field(min_length=1)
    CurrencyKey: str | None = Field(default=None)
    ExternalReference: str | None = Field(default=None, min_length=0, max_length=128)


class PurchaseVoucherUpdateModel(BaseModel):
    """Structural fields from Dinero PurchaseVoucherUpdateModel."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    Lines: list[PurchaseVoucherLineCreateModel]
    VoucherDate: str = Field(min_length=1)
    Timestamp: str = Field(min_length=1)
    DepositAccountNumber: int | None = Field(default=None)
    RegionKey: str | None = Field(default=None)
    FileGuid: str | None = Field(default=None)
    ContactGuid: str
    PaymentDate: str | None = Field(default=None)
    PurchaseType: str = Field(min_length=1)
    CurrencyKey: str | None = Field(default=None)
    ExternalReference: str | None = Field(default=None, min_length=0, max_length=128)


class TimestampObject(BaseModel):
    """Structural fields from Dinero TimestampObject."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    Timestamp: str | None = Field(default=None)


class BookModel(BaseModel):
    """Structural fields from Dinero BookModel."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    Number: int | None = Field(default=None)
    Timestamp: str = Field(min_length=1)


class ApiMailoutModel(BaseModel):
    """Structural fields from Dinero ApiMailoutModel."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    Timestamp: str | None = Field(default=None)
    Sender: str | None = Field(default=None)
    CcToSender: bool | None = Field(default=None)
    Receiver: str | None = Field(default=None)
    Subject: str | None = Field(default=None)
    Message: str | None = Field(default=None)
    AddVoucherAsPdfAttachment: bool | None = Field(default=None)
    ShouldAddTrustPilotEmailAsBcc: bool
