from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.tools import billing, customers, status, support
from app.tools.context import ToolContext
from app.tools.schemas import (
    CancellationData,
    CustomerByIdInput,
    CustomerData,
    CustomerLookupInput,
    EmptyInput,
    InvoiceData,
    PasswordResetData,
    RefundData,
    RefundInput,
    ServiceStatusData,
    SubscriptionData,
    TicketData,
    TicketInput,
)


ToolHandler = Callable[[BaseModel, ToolContext], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_type: Any
    handler: ToolHandler
    permission: Literal["read", "write"]
    confirmation_required: bool = False

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "get_customer": ToolDefinition(
        "get_customer",
        "Look up the customer associated with this support session by email.",
        CustomerLookupInput,
        CustomerData,
        customers.get_customer,
        "read",
    ),
    "get_customer_by_id": ToolDefinition(
        "get_customer_by_id",
        "Look up a customer by ID. Access is restricted to the session's customer.",
        CustomerByIdInput,
        CustomerData,
        customers.get_customer_by_id,
        "read",
    ),
    "get_subscription": ToolDefinition(
        "get_subscription",
        "Get the authenticated customer's subscription plan and status.",
        EmptyInput,
        SubscriptionData,
        customers.get_subscription,
        "read",
    ),
    "get_recent_invoices": ToolDefinition(
        "get_recent_invoices",
        "List recent invoices for the authenticated customer.",
        EmptyInput,
        list[InvoiceData],
        billing.get_recent_invoices,
        "read",
    ),
    "get_support_tickets": ToolDefinition(
        "get_support_tickets",
        "List recent support tickets for the authenticated customer.",
        EmptyInput,
        list[TicketData],
        support.get_support_tickets,
        "read",
    ),
    "check_service_status": ToolDefinition(
        "check_service_status",
        "Read current service health information.",
        EmptyInput,
        list[ServiceStatusData],
        status.check_service_status,
        "read",
    ),
    "create_support_ticket": ToolDefinition(
        "create_support_ticket",
        "Create a support ticket for the authenticated customer.",
        TicketInput,
        TicketData,
        support.create_support_ticket,
        "write",
    ),
    "request_password_reset": ToolDefinition(
        "request_password_reset",
        "Queue a password reset request for the authenticated customer.",
        EmptyInput,
        PasswordResetData,
        billing.request_password_reset,
        "write",
        confirmation_required=True,
    ),
    "request_refund": ToolDefinition(
        "request_refund",
        "Refund one paid invoice belonging to the authenticated customer.",
        RefundInput,
        RefundData,
        billing.request_refund,
        "write",
        confirmation_required=True,
    ),
    "cancel_subscription": ToolDefinition(
        "cancel_subscription",
        "Cancel the authenticated customer's subscription.",
        EmptyInput,
        CancellationData,
        billing.cancel_subscription,
        "write",
        confirmation_required=True,
    ),
}


def get_tool_descriptions() -> list[dict[str, Any]]:
    return [definition.public_schema() for definition in TOOL_REGISTRY.values()]