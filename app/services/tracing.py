from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import AgentTrace


def utcnow() -> datetime:
    """Return a naive UTC timestamp compatible with SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TraceRecorder:
    """Persist observable execution events without recording model reasoning."""

    def __init__(self, db: Session, session_id: str, provider: str) -> None:
        self.db = db
        self.trace = AgentTrace(
            trace_id=str(uuid4()),
            session_id=session_id,
            provider=provider,
            created_at=utcnow(),
            events=[],
        )
        self.db.add(self.trace)
        self.db.flush()
        self.event("run_started", "Received request", status="started")

    @classmethod
    def attach(cls, db: Session, trace: AgentTrace) -> "TraceRecorder":
        """Continue a trace when a pending action is approved or declined."""
        recorder = cls.__new__(cls)
        recorder.db = db
        recorder.trace = trace
        return recorder

    @property
    def trace_id(self) -> str:
        return self.trace.trace_id

    def event(
        self,
        event_type: str,
        message: str,
        *,
        status: str = "info",
        tool_name: str | None = None,
        duration_ms: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "at": utcnow().isoformat(timespec="milliseconds") + "Z",
            "type": event_type,
            "message": message,
            "status": status,
        }
        if tool_name:
            event["tool_name"] = tool_name
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        if details:
            event["details"] = details
        self.trace.events = [*self.trace.events, event]
        self.db.flush()