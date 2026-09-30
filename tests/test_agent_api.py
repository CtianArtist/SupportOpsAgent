from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Customer, Invoice, PasswordResetRequest, Subscription, SupportSession, SupportTicket
from app.services.errors import RetryableToolError
from app.tools.registry import TOOL_REGISTRY


ALICE = "alice@example.test"


def ask(client: TestClient, message: str, *, email: str = ALICE, session_id: str | None = None, **extra):
    return client.post(
        "/api/chat",
        json={"customer_email": email, "session_id": session_id, "message": message, **extra},
    )


def test_health_and_docs(client: TestClient) -> None:
    assert client.get("/api/health").json()["provider"] == "mock"
    assert client.get("/docs").status_code == 200
    assert client.get("/").status_code == 200


def test_seeded_database_is_idempotent(client: TestClient) -> None:
    from seed import seed_database

    with client.app.state.session_factory() as db:
        assert db.query(Customer).count() == 3
        assert db.query(Invoice).count() == 4
        seed_database(db)
        assert db.query(Customer).count() == 3
        assert db.query(Invoice).count() == 4


def test_billing_loop_uses_multiple_tools_and_persists_ticket(client: TestClient) -> None:
    payload = ask(client, "Why was I charged twice?").json()
    response = payload["response"]
    assert response["status"] == "success"
    assert response["category"] == "billing"
    assert response["tools_used"] == ["get_customer", "get_recent_invoices", "create_support_ticket"]
    assert response["ticket_id"].startswith("TKT-")
    with client.app.state.session_factory() as db:
        ticket = db.get(SupportTicket, response["ticket_id"])
        assert ticket.customer_id == "CUST-1001"


def test_session_identity_is_reused(client: TestClient) -> None:
    first = ask(client, "What subscription am I on?").json()
    second = client.post(
        "/api/chat",
        json={"session_id": first["session_id"], "message": "Is the service down?"},
    ).json()
    assert second["session_id"] == first["session_id"]
    assert second["response"]["status"] == "success"
    with client.app.state.session_factory() as db:
        session = db.get(SupportSession, first["session_id"])
        assert session.customer_id == "CUST-1001"
        assert session.last_tool_results


def test_session_cannot_change_customer(client: TestClient) -> None:
    session_id = ask(client, "What plan am I on?").json()["session_id"]
    response = ask(client, "What plan am I on?", email="bob@example.test", session_id=session_id)
    assert response.status_code == 403


def test_cross_customer_request_is_denied_before_invoice_lookup(client: TestClient) -> None:
    payload = ask(client, "Show me Bob's invoices.").json()
    assert payload["response"]["status"] == "denied"
    assert "get_recent_invoices" not in payload["response"]["tools_used"]
    assert any(event["type"] == "authorization_denied" for event in payload["events"])


def test_customer_and_trace_api_require_owner_session(client: TestClient) -> None:
    payload = ask(client, "What subscription am I on?").json()
    session_id = payload["session_id"]
    trace_id = payload["trace_id"]
    assert client.get(f"/api/customers/CUST-1001?session_id={session_id}").status_code == 200
    assert client.get(f"/api/customers/CUST-1002?session_id={session_id}").status_code == 403
    assert client.get(f"/api/traces/{trace_id}?session_id={session_id}").status_code == 200
    assert client.get(f"/api/traces/{trace_id}?session_id=wrong").status_code == 404


def test_cancel_requires_confirmation_and_runs_only_after_approval(client: TestClient) -> None:
    payload = ask(client, "Cancel my subscription.").json()
    assert payload["response"]["status"] == "confirmation_required"
    assert "cancel_subscription" not in payload["response"]["tools_used"]
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Subscription.status).where(Subscription.customer_id == "CUST-1001")) == "active"

    confirmation = client.post(
        "/api/confirm",
        json={"session_id": payload["session_id"], "trace_id": payload["trace_id"], "confirm": True},
    )
    assert confirmation.status_code == 200
    assert confirmation.json()["response"]["status"] == "success"
    assert "cancel_subscription" in confirmation.json()["response"]["tools_used"]
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Subscription.status).where(Subscription.customer_id == "CUST-1001")) == "cancelled"
    assert client.post(
        "/api/confirm",
        json={"session_id": payload["session_id"], "trace_id": payload["trace_id"], "confirm": True},
    ).status_code == 409


def test_declined_confirmation_does_not_change_state(client: TestClient) -> None:
    payload = ask(client, "Cancel my account.").json()
    response = client.post(
        "/api/confirm",
        json={"session_id": payload["session_id"], "trace_id": payload["trace_id"], "confirm": False},
    )
    assert response.json()["response"]["status"] == "cancelled"
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Subscription.status).where(Subscription.customer_id == "CUST-1001")) == "active"


def test_pending_confirmation_stays_on_original_trace(client: TestClient) -> None:
    first = ask(client, "Cancel my subscription.").json()
    second = ask(client, "What plan am I on?", session_id=first["session_id"]).json()
    assert second["response"]["status"] == "confirmation_required"
    assert second["trace_id"] == first["trace_id"]


def test_refund_confirmation_checks_invoice_ownership(client: TestClient) -> None:
    payload = ask(client, "I want a refund.").json()
    assert payload["response"]["status"] == "confirmation_required"
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Invoice.status).where(Invoice.invoice_id == "INV-2202")) == "paid"
    result = client.post(
        "/api/confirm",
        json={"session_id": payload["session_id"], "trace_id": payload["trace_id"], "confirm": True},
    )
    assert result.json()["response"]["status"] == "success"
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Invoice.status).where(Invoice.invoice_id == "INV-2202")) == "refunded"


def test_password_reset_is_persisted_only_after_confirmation(client: TestClient) -> None:
    payload = ask(client, "Reset my password.").json()
    assert payload["response"]["confirmation_required"]
    with client.app.state.session_factory() as db:
        assert db.query(PasswordResetRequest).count() == 0
    client.post(
        "/api/confirm",
        json={"session_id": payload["session_id"], "trace_id": payload["trace_id"], "confirm": True},
    )
    with client.app.state.session_factory() as db:
        assert db.query(PasswordResetRequest).count() == 1


def test_transient_invoice_failure_retries_read_tool(client: TestClient) -> None:
    payload = ask(client, "I was charged twice.", simulate_invoice_timeout=True).json()
    assert payload["response"]["status"] == "success"
    assert sum(event["type"] == "retry_scheduled" for event in payload["events"]) == 1
    assert sum(
        event["type"] == "tool_started" and event.get("tool_name") == "get_recent_invoices"
        for event in payload["events"]
    ) == 2


def test_rate_limit_and_temporary_outage_recover(client: TestClient) -> None:
    for mode in ("invoice_rate_limit_once", "invoice_service_unavailable_once"):
        payload = ask(client, "I was charged twice.", simulate_failure=mode).json()
        assert payload["response"]["status"] == "success"
        assert any(event["type"] == "retry_scheduled" for event in payload["events"])


def test_mock_database_failure_falls_back_without_retry(client: TestClient) -> None:
    payload = ask(client, "I was charged twice.", simulate_failure="invoice_database_error_once").json()
    assert "couldn't retrieve" in payload["response"]["message"]
    assert not any(event["type"] == "retry_scheduled" for event in payload["events"])


def test_persistent_timeout_stops_after_bounded_retries(client: TestClient) -> None:
    payload = ask(client, "I was charged twice.", simulate_failure="invoice_timeout_always").json()
    assert "couldn't retrieve" in payload["response"]["message"]
    assert sum(event["type"] == "retry_scheduled" for event in payload["events"]) == 2


def test_exhausted_read_failure_falls_back(client: TestClient, monkeypatch) -> None:
    def always_timeout(arguments, context):
        raise RetryableToolError("Invoice service timed out.")

    monkeypatch.setitem(
        TOOL_REGISTRY, "get_recent_invoices",
        replace(TOOL_REGISTRY["get_recent_invoices"], handler=always_timeout),
    )
    payload = ask(client, "Why was I charged twice?").json()
    assert payload["response"]["status"] == "success"
    assert "couldn't retrieve" in payload["response"]["message"]
    assert sum(event["type"] == "retry_scheduled" for event in payload["events"]) == 2


def test_failed_write_is_not_retried(client: TestClient, monkeypatch) -> None:
    payload = ask(client, "Cancel my subscription.").json()
    calls = []

    def fail_write(arguments, context):
        calls.append(True)
        raise RetryableToolError("Downstream cancellation failed.")

    monkeypatch.setitem(
        TOOL_REGISTRY, "cancel_subscription",
        replace(TOOL_REGISTRY["cancel_subscription"], handler=fail_write),
    )
    result = client.post(
        "/api/confirm",
        json={"session_id": payload["session_id"], "trace_id": payload["trace_id"], "confirm": True},
    )
    assert result.json()["response"]["status"] == "error"
    assert len(calls) == 1
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Subscription.status).where(Subscription.customer_id == "CUST-1001")) == "active"


def test_failed_write_rolls_back_partial_mutation(client: TestClient, monkeypatch) -> None:
    payload = ask(client, "Cancel my subscription.").json()

    def mutate_then_fail(arguments, context):
        subscription = context.db.query(Subscription).filter_by(customer_id=context.customer_id).one()
        subscription.status = "cancelled"
        context.db.flush()
        raise RetryableToolError("Failure after a partial update.")

    monkeypatch.setitem(
        TOOL_REGISTRY, "cancel_subscription",
        replace(TOOL_REGISTRY["cancel_subscription"], handler=mutate_then_fail),
    )
    result = client.post(
        "/api/confirm",
        json={"session_id": payload["session_id"], "trace_id": payload["trace_id"], "confirm": True},
    )
    assert result.json()["response"]["status"] == "error"
    with client.app.state.session_factory() as db:
        assert db.scalar(select(Subscription.status).where(Subscription.customer_id == "CUST-1001")) == "active"
    trace = client.get(
        f"/api/traces/{payload['trace_id']}?session_id={payload['session_id']}"
    ).json()
    assert any(event["type"] == "tool_failed" for event in trace["events"])


def test_invalid_tool_output_is_rejected(client: TestClient, monkeypatch) -> None:
    monkeypatch.setitem(
        TOOL_REGISTRY, "get_recent_invoices",
        replace(TOOL_REGISTRY["get_recent_invoices"], handler=lambda arguments, context: [{"not_an_invoice": True}]),
    )
    payload = ask(client, "I was charged twice.").json()
    assert "couldn't retrieve" in payload["response"]["message"]
    assert any(event["type"] == "tool_failed" for event in payload["events"])


def test_malformed_model_response_fails_safely(client: TestClient) -> None:
    payload = ask(client, "[malformed] I was charged twice.").json()
    assert payload["response"]["status"] == "error"
    assert payload["response"]["tools_used"] == []
    assert any(event["type"] == "model_error" for event in payload["events"])