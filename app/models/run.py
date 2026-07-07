"""Run management and event tracking: agent_runs and agent_events."""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    tool_calling = "tool_calling"
    waiting = "waiting"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class EventType(str, Enum):
    agent_started = "agent_started"
    reasoning_started = "reasoning_started"
    tool_selected = "tool_selected"
    tool_call_started = "tool_call_started"
    tool_call_completed = "tool_call_completed"
    agent_response = "agent_response"
    agent_completed = "agent_completed"
    memory_update_started = "memory_update_started"
    memory_update_completed = "memory_update_completed"
    error = "error"
    run_cancelled = "run_cancelled"


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status", values_callable=lambda obj: [e.value for e in obj]),
        default=RunStatus.pending,
        nullable=False,
        index=True,
    )
    input: Mapped[str] = mapped_column(nullable=False)
    output: Mapped[str | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(nullable=True)
    started_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["AgentEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentEvent.created_at"
    )

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} status={self.status}>"


class AgentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, name="event_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    run: Mapped["AgentRun"] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return f"<AgentEvent type={self.event_type} run_id={self.run_id}>"