import json
from typing import Any

from app.agent.models import FinalDecision
from app.services.errors import MalformedProviderResponse


def parse_final_response(content: str | None) -> FinalDecision:
    if not content:
        raise MalformedProviderResponse("The model returned an empty response.")
    try:
        payload: Any = json.loads(content)
        return FinalDecision.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as error:
        raise MalformedProviderResponse("The model response was not valid structured output.") from error


def tool_context_json(prompt_tools: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "available_tools": [
                {"name": item["name"], "description": item["description"]}
                for item in prompt_tools
            ],
            "tool_results": results,
        },
        ensure_ascii=False,
        default=str,
    )