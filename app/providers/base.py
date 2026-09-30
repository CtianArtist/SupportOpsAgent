from typing import Protocol

from app.agent.models import AgentDecision, AgentPrompt


class LLMProvider(Protocol):
    name: str

    async def decide(self, prompt: AgentPrompt) -> AgentDecision:
        """Return one validated tool request or one final response."""