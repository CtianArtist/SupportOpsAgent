from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Invoice, SupportSession
from app.services.errors import AuthorizationDenied


def authorize_tool(
    db: Session,
    session: SupportSession,
    tool_name: str,
    arguments: BaseModel,
    customer_email: str,
) -> None:
    """Enforce session ownership independently of provider-selected arguments."""
    data = arguments.model_dump()
    target_id = data.get("customer_id")
    if target_id is not None and target_id != session.customer_id:
        raise AuthorizationDenied("This session cannot access that customer.")

    target_email = data.get("email")
    if target_email is not None and target_email.casefold() != customer_email.casefold():
        raise AuthorizationDenied("This session can only look up its associated customer.")

    if tool_name == "request_refund":
        invoice = db.query(Invoice).filter(Invoice.invoice_id == data.get("invoice_id")).one_or_none()
        if invoice is None or invoice.customer_id != session.customer_id:
            raise AuthorizationDenied("That invoice is not available to this session.")