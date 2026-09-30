import asyncio
from contextlib import nullcontext
from time import perf_counter
from typing import Any

from pydantic import BaseModel, TypeAdapter

from app.services.errors import RetryableToolError, ToolExecutionFailed
from app.services.tracing import TraceRecorder
from app.tools.context import ToolContext
from app.tools.registry import ToolDefinition


async def execute_tool(
    definition: ToolDefinition,
    arguments: BaseModel,
    context: ToolContext,
    trace: TraceRecorder,
    *,
    attempts: int,
    base_delay_seconds: float,
) -> Any:
    """Only read tools may be retried. Writes always execute at most once."""
    limit = max(1, attempts) if definition.permission == "read" else 1
    for attempt in range(1, limit + 1):
        started = perf_counter()
        trace.event(
            "tool_started",
            f"{definition.name} started (attempt {attempt})",
            tool_name=definition.name,
            status="started",
            details={"attempt": attempt, "arguments": arguments.model_dump(mode="json")},
        )
        try:
            # A write executes in a savepoint so a partial mutation can be
            # rolled back without losing the surrounding trace or session.
            transaction = context.db.begin_nested() if definition.permission == "write" else nullcontext()
            with transaction:
                result = definition.handler(arguments, context)
                result = TypeAdapter(definition.output_type).validate_python(result)
            trace.event(
                "tool_succeeded",
                f"{definition.name} succeeded",
                tool_name=definition.name,
                status="success",
                duration_ms=round((perf_counter() - started) * 1000),
                details={"attempt": attempt},
            )
            return result
        except RetryableToolError as error:
            trace.event(
                "tool_failed",
                str(error),
                tool_name=definition.name,
                status="error",
                duration_ms=round((perf_counter() - started) * 1000),
                details={"attempt": attempt, "retryable": definition.permission == "read"},
            )
            if attempt == limit:
                raise ToolExecutionFailed(str(error)) from error
            delay = base_delay_seconds * (2 ** (attempt - 1))
            trace.event(
                "retry_scheduled",
                f"Retrying {definition.name} after {delay:.2f}s",
                tool_name=definition.name,
                details={"next_attempt": attempt + 1, "delay_seconds": delay},
            )
            await asyncio.sleep(delay)
        except Exception as error:
            trace.event(
                "tool_failed",
                f"{definition.name} failed: {type(error).__name__}",
                tool_name=definition.name,
                status="error",
                duration_ms=round((perf_counter() - started) * 1000),
                details={"attempt": attempt, "retryable": False},
            )
            raise ToolExecutionFailed(f"{definition.name} could not complete.") from error
    raise ToolExecutionFailed(f"{definition.name} could not complete.")