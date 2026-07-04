"""Workflow execution audit trail: WorkflowRun (one execution of a
Workflow) and WorkflowRunStep (one executed step within that run).

Append-only, like agent_runs / agent_events - never soft-deleted or
mutated except to advance status, matching the platform's existing audit
strategy (see docs/Architecture.md, soft delete strategy section).
"""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowRunStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"


class WorkflowStepStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"


class WorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[WorkflowRunStatus] = mapped_column(
        SAEnum(
            WorkflowRunStatus,
            name="workflow_run_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=WorkflowRunStatus.pending,
        nullable=False,
        index=True,
    )
    input: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    workflow: Mapped["Workflow"] = relationship()
    session: Mapped["ChatSession"] = relationship()
    steps: Mapped[list["WorkflowRunStep"]] = relationship(
        back_populates="workflow_run", cascade="all, delete-orphan", order_by="WorkflowRunStep.created_at"
    )

    def __repr__(self) -> str:
        return f"<WorkflowRun id={self.id} status={self.status}>"


class WorkflowEventType(str, Enum):
    """Reuses the same append-only event-log PATTERN as app.models.run.EventType
    (one row per observable occurrence, queryable per-run, streamable via
    SSE) - but as a separate table FK'd to workflow_runs rather than
    overloading agent_events.run_id (which is scoped to a single Agent
    run, not a whole multi-step Workflow run). This is "reuse the
    existing event mechanism" in the sense of reusing its design, not
    its physical table, since the parent entity differs.
    """

    workflow_started = "WorkflowStarted"
    workflow_step_started = "WorkflowStepStarted"
    workflow_step_completed = "WorkflowStepCompleted"
    workflow_completed = "WorkflowCompleted"
    workflow_failed = "WorkflowFailed"


class WorkflowEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_events"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[WorkflowEventType] = mapped_column(
        SAEnum(
            WorkflowEventType,
            name="workflow_event_type",
            values_callable=lambda obj: [e.value for e in obj],
        )
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    workflow_run: Mapped["WorkflowRun"] = relationship()

    def __repr__(self) -> str:
        return f"<WorkflowEvent type={self.event_type} workflow_run_id={self.workflow_run_id}>"


class WorkflowRunStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_run_steps"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[WorkflowStepStatus] = mapped_column(
        SAEnum(
            WorkflowStepStatus,
            name="workflow_step_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=WorkflowStepStatus.pending,
        nullable=False,
        index=True,
    )
    started_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    workflow_run: Mapped["WorkflowRun"] = relationship(back_populates="steps")
    workflow_step: Mapped["WorkflowStep"] = relationship()

    def __repr__(self) -> str:
        return f"<WorkflowRunStep run_id={self.workflow_run_id} order={self.step_order} status={self.status}>"
