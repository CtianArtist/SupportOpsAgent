from app.agent.models import AgentDecision, AgentPrompt, FinalDecision, ToolDecision


class MockLLMProvider:
    """Rule-based provider for deterministic offline development and tests."""

    name = "mock"

    async def decide(self, prompt: AgentPrompt) -> AgentDecision:
        text = prompt.user_message.casefold()
        if "[malformed]" in text:
            from app.services.errors import MalformedProviderResponse

            raise MalformedProviderResponse("Mock provider simulated malformed output.")

        results = {item["tool_name"]: item for item in prompt.tool_results}
        if "bob" in text and ("invoice" in text or "billing" in text or "charges" in text):
            return ToolDecision(
                tool_name="get_customer",
                arguments={"email": "bob@example.test"},
            )

        if any(word in text for word in ("down", "outage", "service status", "service down")):
            if "check_service_status" not in results:
                return ToolDecision(tool_name="check_service_status", arguments={})
            statuses = results["check_service_status"].get("data") or []
            status = statuses[0].get("status", "unknown") if statuses else "unknown"
            return FinalDecision(
                category="service_status",
                message=(
                    "The Core API is currently operational. I did not find an active service issue."
                    if status == "operational"
                    else f"The service status is {status}. I found the latest status update for you."
                ),
            )

        if "cancel" in text and any(word in text for word in ("subscription", "account", "plan")):
            if "get_subscription" not in results:
                return ToolDecision(tool_name="get_subscription", arguments={})
            if not results["get_subscription"].get("ok", True):
                return FinalDecision(category="account", message="I couldn't check your subscription right now, so I have not cancelled it.")
            return ToolDecision(tool_name="cancel_subscription", arguments={})

        if any(word in text for word in ("reset my password", "password reset", "reset password")):
            return ToolDecision(tool_name="request_password_reset", arguments={})

        if "refund" in text:
            if "get_customer" not in results:
                return ToolDecision(tool_name="get_customer", arguments={"email": prompt.customer_email})
            if "get_recent_invoices" not in results:
                return ToolDecision(tool_name="get_recent_invoices", arguments={})
            invoices = results["get_recent_invoices"].get("data") or []
            paid = next((row for row in invoices if row.get("status") == "paid"), None)
            if paid:
                return ToolDecision(
                    tool_name="request_refund",
                    arguments={
                        "invoice_id": paid["invoice_id"],
                        "reason": "Customer requested a refund.",
                    },
                )
            return FinalDecision(
                category="billing",
                message="I could not find a paid invoice eligible for a refund on this account.",
            )

        if any(word in text for word in ("subscription", "plan", "monthly price")):
            if "get_customer" not in results:
                return ToolDecision(tool_name="get_customer", arguments={"email": prompt.customer_email})
            if "get_subscription" not in results:
                return ToolDecision(tool_name="get_subscription", arguments={})
            data = results["get_subscription"].get("data") or {}
            return FinalDecision(
                category="account",
                message=(
                    f"Your {data.get('plan', 'current')} plan is {data.get('status', 'unknown')} "
                    f"at ${data.get('price_cents', 0) / 100:.2f} per month."
                ),
            )

        if any(phrase in text for phrase in ("my tickets", "recent tickets", "list tickets", "show tickets")):
            if "get_support_tickets" not in results:
                return ToolDecision(tool_name="get_support_tickets", arguments={})
            tickets = results["get_support_tickets"].get("data") or []
            return FinalDecision(category="support", message=f"You have {len(tickets)} recent support ticket(s).")

        if any(word in text for word in ("ticket", "can't log in", "cannot log in", "can't login", "can't sign in")):
            if "get_customer" not in results:
                return ToolDecision(tool_name="get_customer", arguments={"email": prompt.customer_email})
            category = "access" if any(word in text for word in ("log in", "login", "sign in")) else "technical"
            summary = "Customer cannot log in" if category == "access" else "Customer support request"
            if "create_support_ticket" not in results:
                return ToolDecision(
                    tool_name="create_support_ticket",
                    arguments={"category": category, "summary": summary, "priority": "normal"},
                )
            ticket = results["create_support_ticket"].get("data") or {}
            return FinalDecision(
                category=category,
                message=f"I created support ticket {ticket.get('ticket_id', 'for you')} and marked it as open.",
            )

        if any(word in text for word in ("charged twice", "charged two", "duplicate", "invoice", "billing", "charge")):
            if "get_customer" not in results:
                return ToolDecision(tool_name="get_customer", arguments={"email": prompt.customer_email})
            if "get_recent_invoices" not in results:
                return ToolDecision(tool_name="get_recent_invoices", arguments={})
            invoices = results["get_recent_invoices"].get("data") or []
            if not results["get_recent_invoices"].get("ok", True):
                return FinalDecision(
                    category="billing",
                    message="I couldn't retrieve your invoices right now. The invoice service timed out; please try again shortly.",
                )
            if "create_support_ticket" not in results and len(invoices) >= 2:
                return ToolDecision(
                    tool_name="create_support_ticket",
                    arguments={
                        "category": "billing",
                        "summary": "Review possible duplicate subscription charge",
                        "priority": "high",
                    },
                )
            duplicate = len(invoices) >= 2 and any(
                row.get("description", "").lower().startswith("duplicate") for row in invoices
            )
            if duplicate:
                ticket = results.get("create_support_ticket", {}).get("data") or {}
                ticket_text = (
                    f" I opened billing ticket {ticket.get('ticket_id')} for review."
                    if ticket.get("ticket_id")
                    else ""
                )
                return FinalDecision(
                    category="billing",
                    message=(
                        "I found two $29.00 Pro charges this month. The second charge is marked as a "
                        "possible duplicate." + ticket_text
                    ),
                )
            return FinalDecision(
                category="billing",
                message=f"I found {len(invoices)} recent invoice(s) and did not find a duplicate charge.",
            )

        if "get_customer" not in results:
            return ToolDecision(tool_name="get_customer", arguments={"email": prompt.customer_email})
        return FinalDecision(
            category="general",
            message="I can help with billing, subscriptions, account access, support tickets, or service status. What would you like to check?",
        )