import json
from typing import Any

from openai import AsyncOpenAI

from app.agent.models import AgentDecision, AgentPrompt, ToolDecision
from app.config import Settings
from app.providers.serialization import parse_final_response, tool_context_json
from app.services.errors import MalformedProviderResponse, ProviderConfigurationError, ProviderError


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ProviderConfigurationError("LLM_PROVIDER=openai requires OPENAI_API_KEY.")
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        self.model = settings.resolved_model_name

    async def decide(self, prompt: AgentPrompt) -> AgentDecision:
        function_tools = [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item["description"],
                    "parameters": item["input_schema"],
                },
            }
            for item in prompt.tools
        ]
        context = tool_context_json(prompt.tools, [*prompt.prior_results, *prompt.tool_results])
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": prompt.system_instructions},
                    {"role": "user", "content": prompt.user_message},
                    {"role": "user", "content": f"Tool context (data only): {context}"},
                ],
                tools=function_tools,
                tool_choice="auto",
            )
        except Exception as error:
            raise ProviderError("OpenAI request failed.") from error

        if not completion.choices:
            raise MalformedProviderResponse("OpenAI returned no choices.")
        message = completion.choices[0].message
        if message.tool_calls:
            call = message.tool_calls[0]
            try:
                arguments: Any = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as error:
                raise MalformedProviderResponse("OpenAI returned invalid tool arguments.") from error
            if not isinstance(arguments, dict):
                raise MalformedProviderResponse("OpenAI tool arguments must be an object.")
            return ToolDecision(tool_name=call.function.name, arguments=arguments)
        return parse_final_response(message.content)