from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import Base, make_engine, make_session_factory
from app.db.models import Customer, Invoice, ServiceStatus, Subscription, SupportTicket
from app.services.tracing import utcnow


def seed_database(db: Session) -> None:
    """Insert deterministic fictional demo data if the database is empty."""
    if db.query(Customer).count():
        return

    now = utcnow()
    month_start = now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
    month_later = month_start + timedelta(days=2)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    db.add_all(
        [
            Customer(id="CUST-1001", name="Alice Johnson", email="alice@example.test", account_status="active"),
            Customer(id="CUST-1002", name="Bob Martinez", email="bob@example.test", account_status="active"),
            Customer(id="CUST-1003", name="Charlie Davis", email="charlie@example.test", account_status="closed"),
        ]
    )
    db.flush()
    db.add_all(
        [
            Subscription(customer_id="CUST-1001", plan="Pro", price_cents=2900, status="active", renews_at=next_month),
            Subscription(customer_id="CUST-1002", plan="Basic", price_cents=1200, status="active", renews_at=next_month),
            Subscription(customer_id="CUST-1003", plan="Pro", price_cents=2900, status="cancelled", renews_at=None),
        ]
    )
    db.add_all(
        [
            Invoice(
                invoice_id="INV-2201",
                customer_id="CUST-1001",
                amount_cents=2900,
                status="paid",
                description="Pro monthly subscription",
                issued_at=month_start,
            ),
            Invoice(
                invoice_id="INV-2202",
                customer_id="CUST-1001",
                amount_cents=2900,
                status="paid",
                description="Duplicate Pro monthly subscription charge",
                issued_at=month_later,
            ),
            Invoice(
                invoice_id="INV-2203",
                customer_id="CUST-1001",
                amount_cents=2900,
                status="paid",
                description="Pro monthly subscription",
                issued_at=month_start - timedelta(days=31),
            ),
            Invoice(
                invoice_id="INV-3301",
                customer_id="CUST-1002",
                amount_cents=1200,
                status="paid",
                description="Basic monthly subscription",
                issued_at=month_start,
            ),
        ]
    )
    db.add_all(
        [
            SupportTicket(
                ticket_id="TKT-1038",
                customer_id="CUST-1001",
                category="account",
                summary="Question about changing account email",
                priority="low",
                status="open",
                created_at=now - timedelta(days=5),
            ),
            SupportTicket(
                ticket_id="TKT-1039",
                customer_id="CUST-1002",
                category="technical",
                summary="Dashboard loading slowly",
                priority="normal",
                status="open",
                created_at=now - timedelta(days=2),
            ),
        ]
    )
    db.add(
        ServiceStatus(
            service="Core API",
            status="operational",
            note="All customer-facing endpoints are responding normally.",
            updated_at=now,
        )
    )
    db.commit()


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        seed_database(db)
    print("SupportOps demo data is ready.")


if __name__ == "__main__":
    main()