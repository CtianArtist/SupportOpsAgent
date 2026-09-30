from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.agent.engine import AgentEngine
from app.agent.models import ChatEnvelope, ChatRequest, ConfirmRequest
from app.config import Settings, get_settings
from app.db.database import Base, get_db, make_engine, make_session_factory
from app.db.models import AgentTrace, Customer, Subscription, SupportSession
from app.providers.base import LLMProvider
from app.providers.factory import create_provider
from app.services.tracing import utcnow
from seed import seed_database


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def resolve_session(db: Session, session_id: str | None, email: str | None) -> tuple[SupportSession, Customer]:
    """Demo identity is fixed when a session is created and cannot be switched."""
    if session_id:
        support_session = db.get(SupportSession, session_id)
        if support_session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        customer = db.get(Customer, support_session.customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="Session customer not found.")
        if email and email.casefold() != customer.email.casefold():
            raise HTTPException(status_code=403, detail="This session belongs to a different customer.")
        return support_session, customer
    if not email:
        raise HTTPException(status_code=400, detail="Customer email is required for a new session.")
    customer = db.query(Customer).filter(Customer.email == email.strip().casefold()).one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Demo customer not found.")
    now = utcnow()
    support_session = SupportSession(
        session_id=str(uuid4()),
        customer_id=customer.id,
        pending_confirmation=None,
        last_tool_results=[],
        created_at=now,
        updated_at=now,
    )
    db.add(support_session)
    db.flush()
    return support_session, customer


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    provider: LLMProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    database_engine = engine or make_engine(settings.database_url)
    session_factory = make_session_factory(database_engine)
    selected_provider = provider or create_provider(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        Base.metadata.create_all(database_engine)
        with session_factory() as db:
            seed_database(db)
        yield

    application = FastAPI(
        title="SupportOps Agent",
        description="An observable, permissioned AI customer-support agent demo.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.session_factory = session_factory
    application.state.agent = AgentEngine(selected_provider, settings)
    application.state.settings = settings
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def homepage() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "provider": selected_provider.name, "model": (
            "deterministic-rules" if selected_provider.name == "mock" else settings.resolved_model_name
        )}

    @application.post("/api/chat", response_model=ChatEnvelope)
    async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatEnvelope:
        if selected_provider.name != "mock" and (payload.simulate_failure or payload.simulate_invoice_timeout):
            raise HTTPException(status_code=400, detail="Failure simulation is only available with the Mock provider.")
        support_session, customer = resolve_session(db, payload.session_id, payload.customer_email)
        return await application.state.agent.run(
            db,
            support_session,
            customer,
            payload.message,
            simulate_invoice_timeout=payload.simulate_invoice_timeout,
            simulate_failure=payload.simulate_failure,
        )

    @application.post("/api/confirm", response_model=ChatEnvelope)
    async def confirm(payload: ConfirmRequest, db: Session = Depends(get_db)) -> ChatEnvelope:
        support_session, customer = resolve_session(db, payload.session_id, None)
        result = await application.state.agent.confirm(
            db, support_session, customer, payload.trace_id, payload.confirm
        )
        if result is None:
            raise HTTPException(status_code=409, detail="No matching pending confirmation.")
        return result

    @application.get("/api/traces/{trace_id}")
    def get_trace(
        trace_id: str,
        session_id: str = Query(..., description="The session that owns this trace"),
        db: Session = Depends(get_db),
    ) -> dict:
        trace = db.get(AgentTrace, trace_id)
        if trace is None or trace.session_id != session_id:
            raise HTTPException(status_code=404, detail="Trace not found.")
        return {
            "trace_id": trace.trace_id,
            "session_id": trace.session_id,
            "provider": trace.provider,
            "created_at": trace.created_at.isoformat() + "Z",
            "events": trace.events,
        }

    @application.get("/api/customers/{customer_id}")
    def get_customer(
        customer_id: str,
        session_id: str = Query(..., description="The session that owns this customer"),
        db: Session = Depends(get_db),
    ) -> dict:
        support_session, customer = resolve_session(db, session_id, None)
        if support_session.customer_id != customer_id:
            raise HTTPException(status_code=403, detail="Access denied for this customer.")
        subscription = (
            db.query(Subscription)
            .filter(Subscription.customer_id == customer.id)
            .one_or_none()
        )
        return {
            "customer_id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "account_status": customer.account_status,
            "subscription": {
                "plan": subscription.plan,
                "price_cents": subscription.price_cents,
                "status": subscription.status,
            } if subscription else None,
        }

    return application


app = create_app()