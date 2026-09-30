from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass
class ToolContext:
    """Scoped resources available to one agent run."""

    db: Session
    customer_id: str
    customer_email: str
    failure_mode: str | None = None
    invoice_failure_count: int = 0