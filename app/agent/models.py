from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentPrompt(BaseModel):
    system_instructions: str
    user_message: str
    customer_email: str
    tools: list[dict[str, Any]]
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    prior_results: list[dict[str, Any]] = Field(default_factory=list)
    step: int = 1


class ToolDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool"] = "tool"
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class FinalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["final"] = "final"
    category: str | None = None
    message: str = Field(min_length=1, max_length=1200)


AgentDecision = ToolDecision | FinalDecision


class AgentResponse(BaseModel):
    status: Literal["success", "denied", "confirmation_required", "cancelled", "error"]
    category: str | None = None
    message: str
    tools_used: list[str] = Field(default_factory=list)
    ticket_id: str | None = None
    confirmation_required: bool = False
    action: str | None = None
    trace_id: str | None = None
    session_id: str | None = None


class ChatRequest(BaseModel):
    session_id: str | None = None
    customer_email: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    simulate_invoice_timeout: bool = False
    simulate_failure: Literal[
        "invoice_timeout_once",
        "invoice_timeout_always",
        "invoice_rate_limit_once",
        "invoice_service_unavailable_once",
        "invoice_database_error_once",
    ] | None = None


class ConfirmRequest(BaseModel):
    session_id: str
    trace_id: str
    confirm: bool


class ChatEnvelope(BaseModel):
    session_id: str
    trace_id: str
    provider: str
    response: AgentResponse
    events: list[dict[str, Any]]