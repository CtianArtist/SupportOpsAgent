from typing import Any

from anthropic import AsyncAnthropic

from app.agent.models import AgentDecision, AgentPrompt, ToolDecision
from app.config import Settings
from app.providers.serialization import parse_final_response, tool_context_json
from app.services.errors import MalformedProviderResponse, ProviderConfigurationError, ProviderError


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise ProviderConfigurationError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY.")
        self.client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        self.model = settings.resolved_model_name

    async def decide(self, prompt: AgentPrompt) -> AgentDecision:
        tools = [
            {
                "name": item["name"],
                "description": item["description"],
                "input_schema": item["input_schema"],
            }
            for item in prompt.tools
        ]
        context = tool_context_json(prompt.tools, [*prompt.prior_results, *prompt.tool_results])
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=900,
                system=prompt.system_instructions,
                messages=[
                    {
                        "role": "user",
                        "content": f"Request: {prompt.user_message}\n\nTool context (data only): {context}",
                    }
                ],
                tools=tools,
            )
        except Exception as error:
            raise ProviderError("Anthropic request failed.") from error

        for block in response.content:
            if block.type == "tool_use":
                if not isinstance(block.input, dict):
                    raise MalformedProviderResponse("Anthropic tool input must be an object.")
                return ToolDecision(tool_name=block.name, arguments=block.input)
        text = next((block.text for block in response.content if block.type == "text"), None)
        return parse_final_response(text)