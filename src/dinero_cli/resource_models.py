"""Structural payload models; unknown API fields are retained by the command boundary."""

from pydantic import BaseModel, ConfigDict, Field


class ContactBody(BaseModel):
    """Validate ContactCreateModel structure without filling API defaults."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    ContactGuid: str | None = Field(default=None)
    ExternalReference: str | None = Field(default=None, min_length=0, max_length=128)
    Name: str = Field(min_length=1)
    Street: str | None = Field(default=None)
    ZipCode: str | None = Field(default=None)
    City: str | None = Field(default=None)
    CountryKey: str = Field(min_length=1)
    Phone: str | None = Field(default=None)
    Email: str | None = Field(default=None)
    Webpage: str | None = Field(default=None)
    AttPerson: str | None = Field(default=None)
    VatNumber: str | None = Field(default=None)
    EanNumber: str | None = Field(default=None)
    SENumber: str | None = Field(default=None)
    PNumber: str | None = Field(default=None)
    PaymentConditionType: str | None = Field(default=None)
    PaymentConditionNumberOfDays: int | None = Field(default=None)
    IsPerson: bool
    IsMember: bool
    MemberNumber: str | None = Field(default=None)
    UseCvr: bool
    CompanyTypeKey: str | None = Field(default=None)
    InvoiceMailOutOptionKey: str | None = Field(default=None)
    PreferredInvoiceLanguageKey: str | None = Field(default=None)
    PreferredInvoiceCurrencyKey: str | None = Field(default=None)


class ProductBody(BaseModel):
    """Validate ProductCreateModel structure without filling API defaults."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    ProductNumber: str | None = Field(default=None)
    Name: str | None = Field(default=None)
    BaseAmountValue: float
    Quantity: float
    AccountNumber: int
    Unit: str = Field(min_length=1)
    ExternalReference: str | None = Field(default=None, min_length=0, max_length=128)
    Comment: str | None = Field(default=None, min_length=0, max_length=128)
