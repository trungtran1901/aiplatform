from __future__ import annotations

from datetime import datetime
from uuid import UUID


from app.models.run import EventType, RunStatus
from app.schemas.common import TimestampedSchema


class AgentRunRead(TimestampedSchema):
    session_id: UUID
    agent_id: UUID
    status: RunStatus
    input: str
    output: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class AgentEventRead(TimestampedSchema):
    run_id: UUID
    event_type: EventType
    payload: dict | None = None
