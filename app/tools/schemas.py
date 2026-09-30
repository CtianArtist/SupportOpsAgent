from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyInput(ToolInput):
    pass


class CustomerLookupInput(ToolInput):
    email: str = Field(min_length=3, max_length=254)


class CustomerByIdInput(ToolInput):
    customer_id: str = Field(min_length=1, max_length=32)


class TicketInput(ToolInput):
    category: Literal["billing", "access", "technical", "account"]
    summary: str = Field(min_length=8, max_length=300)
    priority: Literal["low", "normal", "high"] = "normal"


class RefundInput(ToolInput):
    invoice_id: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=8, max_length=300)


class CustomerData(BaseModel):
    customer_id: str
    name: str
    email: str
    account_status: str


class SubscriptionData(BaseModel):
    plan: str
    price_cents: int
    status: str
    renews_at: datetime | None


class InvoiceData(BaseModel):
    invoice_id: str
    amount_cents: int
    status: str
    description: str
    issued_at: datetime


class TicketData(BaseModel):
    ticket_id: str
    category: str
    summary: str
    priority: str
    status: str
    created_at: datetime


class ServiceStatusData(BaseModel):
    service: str
    status: str
    note: str
    updated_at: datetime


class PasswordResetData(BaseModel):
    request_id: str
    status: Literal["queued"]


class RefundData(BaseModel):
    invoice_id: str
    status: Literal["refunded"]


class CancellationData(BaseModel):
    status: Literal["cancelled"]
    plan: str | None = None
    message: str | None = None