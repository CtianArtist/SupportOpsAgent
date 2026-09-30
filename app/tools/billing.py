from uuid import uuid4

from sqlalchemy import desc

from app.db.models import Invoice, PasswordResetRequest, Subscription
from app.services.errors import RateLimitToolError, RetryableToolError, TemporaryServiceError
from app.services.tracing import utcnow
from app.tools.context import ToolContext
from app.tools.schemas import CancellationData, EmptyInput, InvoiceData, PasswordResetData, RefundData, RefundInput


def get_recent_invoices(arguments: EmptyInput, context: ToolContext) -> list[InvoiceData]:
    failure_mode = context.failure_mode
    if failure_mode:
        context.invoice_failure_count += 1
        should_fail = failure_mode == "invoice_timeout_always" or context.invoice_failure_count == 1
        if should_fail:
            if failure_mode.startswith("invoice_timeout"):
                raise RetryableToolError("Invoice service timed out.")
            if failure_mode == "invoice_rate_limit_once":
                raise RateLimitToolError("Invoice service rate limit reached.")
            if failure_mode == "invoice_service_unavailable_once":
                raise TemporaryServiceError("Invoice service temporarily unavailable.")
            if failure_mode == "invoice_database_error_once":
                raise RuntimeError("Simulated invoice database error.")
    invoices = (
        context.db.query(Invoice)
        .filter(Invoice.customer_id == context.customer_id)
        .order_by(desc(Invoice.issued_at))
        .limit(8)
        .all()
    )
    return [
        InvoiceData(
            invoice_id=row.invoice_id,
            amount_cents=row.amount_cents,
            status=row.status,
            description=row.description,
            issued_at=row.issued_at,
        )
        for row in invoices
    ]


def request_password_reset(arguments: EmptyInput, context: ToolContext) -> PasswordResetData:
    request_id = str(uuid4())
    context.db.add(
        PasswordResetRequest(
            request_id=request_id,
            customer_id=context.customer_id,
            status="queued",
            created_at=utcnow(),
        )
    )
    return PasswordResetData(request_id=request_id, status="queued")


def request_refund(arguments: RefundInput, context: ToolContext) -> RefundData:
    invoice = (
        context.db.query(Invoice)
        .filter(
            Invoice.invoice_id == arguments.invoice_id,
            Invoice.customer_id == context.customer_id,
        )
        .one_or_none()
    )
    if invoice is None:
        raise LookupError("Invoice not found for this account.")
    if invoice.status != "paid":
        raise ValueError(f"Invoice is {invoice.status}; only paid invoices can be refunded.")
    invoice.status = "refunded"
    return RefundData(invoice_id=invoice.invoice_id, status="refunded")


def cancel_subscription(arguments: EmptyInput, context: ToolContext) -> CancellationData:
    subscription = (
        context.db.query(Subscription)
        .filter(Subscription.customer_id == context.customer_id)
        .one_or_none()
    )
    if subscription is None:
        raise LookupError("No subscription was found for this account.")
    if subscription.status == "cancelled":
        return CancellationData(status="cancelled", message="The subscription was already cancelled.")
    subscription.status = "cancelled"
    return CancellationData(status="cancelled", plan=subscription.plan)