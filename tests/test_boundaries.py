import asyncio
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.models import AgentPrompt, FinalDecision, ToolDecision
from app.config import Settings
from app.db.database import make_engine
from app.main import create_app
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.factory import create_provider
from app.providers.mock_provider import MockLLMProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.serialization import parse_final_response
from app.services.errors import MalformedProviderResponse, ProviderConfigurationError
from app.tools.schemas import CustomerByIdInput, TicketInput


class ScriptedProvider:
    name = "mock"

    def __init__(self, tool: str, arguments: dict) -> None:
        self.tool = tool
        self.arguments = arguments

    async def decide(self, prompt):
        return ToolDecision(tool_name=self.tool, arguments=self.arguments)


def run_scripted(tool: str, arguments: dict) -> dict:
    settings = Settings(SUPPORTOPS_DATABASE_URL="sqlite://", max_agent_steps=2)
    app = create_app(settings, engine=make_engine("sqlite://"), provider=ScriptedProvider(tool, arguments))
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"customer_email": "alice@example.test", "message": "scripted request"},
        )
    assert response.status_code == 200
    return response.json()


def test_unauthorized_customer_id_is_denied_in_tool_layer() -> None:
    payload = run_scripted("get_customer_by_id", {"customer_id": "CUST-1002"})
    assert payload["response"]["status"] == "denied"
    assert not any(event["type"] == "tool_started" for event in payload["events"])


def test_unauthorized_refund_is_denied_before_confirmation() -> None:
    payload = run_scripted(
        "request_refund",
        {"invoice_id": "INV-3301", "reason": "I would like my money back."},
    )
    assert payload["response"]["status"] == "denied"
    assert not any(event["type"] == "confirmation_required" for event in payload["events"])


def test_invalid_tool_arguments_rejected() -> None:
    payload = run_scripted("create_support_ticket", {"category": "billing", "summary": "short"})
    assert payload["response"]["status"] == "error"
    assert any(event["type"] == "tool_rejected" for event in payload["events"])


def test_unknown_tool_rejected() -> None:
    payload = run_scripted("run_sql", {"query": "SELECT * FROM customers"})
    assert payload["response"]["status"] == "error"
    assert not any(event["type"] == "tool_started" for event in payload["events"])


def test_max_steps_stops_repeated_tool_calls() -> None:
    payload = run_scripted("get_subscription", {})
    assert payload["response"]["status"] == "error"
    assert payload["response"]["tools_used"] == ["get_subscription", "get_subscription"]
    assert any(event["type"] == "step_limit" for event in payload["events"])


def test_input_models_forbid_extra_arguments() -> None:
    with pytest.raises(ValidationError):
        CustomerByIdInput.model_validate({"customer_id": "CUST-1001", "sql": "DROP TABLE customers"})
    with pytest.raises(ValidationError):
        TicketInput.model_validate({"category": "other", "summary": "This is a valid length"})


def test_provider_selection_is_configuration_only() -> None:
    assert isinstance(create_provider(Settings(llm_provider="mock")), MockLLMProvider)
    with pytest.raises(ProviderConfigurationError):
        OpenAIProvider(Settings(llm_provider="openai", openai_api_key=None))
    with pytest.raises(ProviderConfigurationError):
        AnthropicProvider(Settings(llm_provider="anthropic", anthropic_api_key=None))
    assert isinstance(create_provider(Settings(llm_provider="openai", openai_api_key="test-value")), OpenAIProvider)
    assert isinstance(create_provider(Settings(llm_provider="anthropic", anthropic_api_key="test-value")), AnthropicProvider)


def test_real_providers_have_bounded_call_time_and_no_hidden_sdk_retries() -> None:
    settings = Settings(llm_timeout_seconds=12.5)
    for provider in (
        OpenAIProvider(settings.model_copy(update={"openai_api_key": "test-value"})),
        AnthropicProvider(settings.model_copy(update={"anthropic_api_key": "test-value"})),
    ):
        assert provider.client.timeout == 12.5
        assert provider.client.max_retries == 0


def test_provider_failure_returns_safe_error_instead_of_http_500() -> None:
    class BrokenProvider:
        name = "broken"

        async def decide(self, prompt):
            raise RuntimeError("Provider unexpectedly failed.")

    app = create_app(
        Settings(SUPPORTOPS_DATABASE_URL="sqlite://"),
        engine=make_engine("sqlite://"),
        provider=BrokenProvider(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"customer_email": "alice@example.test", "message": "What plan am I on?"},
        )
    assert response.status_code == 200
    assert response.json()["response"]["status"] == "error"
    assert any(event["type"] == "model_error" for event in response.json()["events"])


def test_empty_openai_choices_are_reported_as_malformed() -> None:
    class EmptyCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[])

    provider = OpenAIProvider(Settings(openai_api_key="test-value"))
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=EmptyCompletions()))
    prompt = AgentPrompt(
        system_instructions="Return JSON.",
        user_message="Hello",
        customer_email="alice@example.test",
        tools=[],
    )
    with pytest.raises(MalformedProviderResponse):
        asyncio.run(provider.decide(prompt))


def provider_prompt() -> AgentPrompt:
    return AgentPrompt(
        system_instructions="Return structured decisions.",
        user_message="What plan am I on?",
        customer_email="alice@example.test",
        tools=[
            {
                "name": "get_subscription",
                "description": "Read this customer's plan.",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )


def test_openai_adapter_parses_tool_and_final_without_network() -> None:
    class FakeCompletions:
        def __init__(self) -> None:
            self.message = SimpleNamespace(
                tool_calls=[SimpleNamespace(function=SimpleNamespace(name="get_subscription", arguments="{}"))],
                content=None,
            )

        async def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=self.message)])

    provider = OpenAIProvider(Settings(openai_api_key="test-value"))
    completions = FakeCompletions()
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    tool = asyncio.run(provider.decide(provider_prompt()))
    assert isinstance(tool, ToolDecision)
    assert (tool.tool_name, tool.arguments) == ("get_subscription", {})

    completions.message = SimpleNamespace(
        tool_calls=None,
        content='{"kind":"final","category":"account","message":"You are on Pro."}',
    )
    final = asyncio.run(provider.decide(provider_prompt()))
    assert isinstance(final, FinalDecision)
    assert final.message == "You are on Pro."


def test_anthropic_adapter_parses_tool_and_final_without_network() -> None:
    class FakeMessages:
        def __init__(self) -> None:
            self.content = [SimpleNamespace(type="tool_use", name="get_subscription", input={})]

        async def create(self, **kwargs):
            return SimpleNamespace(content=self.content)

    provider = AnthropicProvider(Settings(anthropic_api_key="test-value"))
    messages = FakeMessages()
    provider.client = SimpleNamespace(messages=messages)
    tool = asyncio.run(provider.decide(provider_prompt()))
    assert isinstance(tool, ToolDecision)
    assert (tool.tool_name, tool.arguments) == ("get_subscription", {})

    messages.content = [SimpleNamespace(type="text", text='{"kind":"final","category":"account","message":"You are on Pro."}')]
    final = asyncio.run(provider.decide(provider_prompt()))
    assert isinstance(final, FinalDecision)
    assert final.message == "You are on Pro."


def test_final_response_requires_structured_output() -> None:
    assert parse_final_response('{"kind":"final","category":"billing","message":"Resolved."}').category == "billing"
    with pytest.raises(MalformedProviderResponse):
        parse_final_response("Here is your answer.")