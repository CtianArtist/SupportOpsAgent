from uuid import uuid4

from sqlalchemy import desc

from app.db.models import SupportTicket
from app.services.tracing import utcnow
from app.tools.context import ToolContext
from app.tools.schemas import EmptyInput, TicketData, TicketInput


def get_support_tickets(arguments: EmptyInput, context: ToolContext) -> list[TicketData]:
    rows = (
        context.db.query(SupportTicket)
        .filter(SupportTicket.customer_id == context.customer_id)
        .order_by(desc(SupportTicket.created_at))
        .limit(10)
        .all()
    )
    return [
        TicketData(
            ticket_id=row.ticket_id,
            category=row.category,
            summary=row.summary,
            priority=row.priority,
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]


def create_support_ticket(arguments: TicketInput, context: ToolContext) -> TicketData:
    ticket = SupportTicket(
        ticket_id=f"TKT-{uuid4().hex[:7].upper()}",
        customer_id=context.customer_id,
        category=arguments.category,
        summary=arguments.summary,
        priority=arguments.priority,
        status="open",
        created_at=utcnow(),
    )
    context.db.add(ticket)
    context.db.flush()
    return TicketData(
        ticket_id=ticket.ticket_id,
        category=ticket.category,
        summary=ticket.summary,
        priority=ticket.priority,
        status=ticket.status,
        created_at=ticket.created_at,
    )