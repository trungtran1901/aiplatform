"""Execution Engine audit trail - AgentX Runtime v2 (Phase 9, flagged).

Append-only, mirrors app.models.workflow_run's shape (WorkflowRun/
WorkflowRunStep) but for ad-hoc ExecutionPlans (app.planning.models)
that were never saved as Workflow metadata - e.g. a plan the Planning
Engine assembled on the fly for one chat turn.
"""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExecutionPlanRunStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"


class ExecutionStepStatus(str, Enum):
    pending = "PENDING"
    running = "RUNNING"
    retrying = "RETRYING"
    completed = "COMPLETED"
    failed = "FAILED"


class ExecutionPlanRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "execution_plan_runs"

    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExecutionPlanRunStatus] = mapped_column(
        SAEnum(ExecutionPlanRunStatus, name="execution_plan_run_status", values_callable=lambda o: [e.value for e in o]),
        default=ExecutionPlanRunStatus.pending, nullable=False, index=True,
    )
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["ExecutionPlanStepRun"]] = relationship(
        back_populates="plan_run", cascade="all, delete-orphan", order_by="ExecutionPlanStepRun.step_order"
    )

    def __repr__(self) -> str:
        return f"<ExecutionPlanRun id={self.id} status={self.status}>"


class ExecutionPlanStepRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "execution_plan_step_runs"

    plan_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_plan_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_code: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ExecutionStepStatus] = mapped_column(
        SAEnum(ExecutionStepStatus, name="execution_step_status", values_callable=lambda o: [e.value for e in o]),
        default=ExecutionStepStatus.pending, nullable=False, index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)

    plan_run: Mapped["ExecutionPlanRun"] = relationship(back_populates="steps")

    def __repr__(self) -> str:
        return f"<ExecutionPlanStepRun plan_run_id={self.plan_run_id} order={self.step_order} status={self.status}>"
