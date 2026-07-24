"""Workflow Scheduling - runs a Workflow automatically on a cron or
interval basis.

Deliberately NOT a full cron-in-DB engine: this table only stores WHAT
to run and WHEN it's next due (next_run_at, computed by
WorkflowScheduleService using croniter / a plain interval add). The
actual ticking loop lives in app/schedule/ticker.py and is a separate
concern from this metadata - same "metadata vs execution" split as
Workflow/WorkflowStep vs WorkflowExecutor.

Cross-instance safety: this runtime is stateless and horizontally
scalable (see docs/Architecture.md), so multiple replicas could all
poll this table at the same tick. Actual triggering is coordinated via
a short-lived Redis lock (app/schedule/ticker.py), not by anything in
this model - this table is agnostic to how many replicas exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ScheduleType(str, Enum):
    cron = "CRON"
    interval = "INTERVAL"


class WorkflowSchedule(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "workflow_schedules"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_type: Mapped[ScheduleType] = mapped_column(
        SAEnum(ScheduleType, name="schedule_type", values_callable=lambda o: [e.value for e in o]),
        nullable=False,
    )
    # Required when schedule_type=CRON, e.g. "0 9 * * MON-FRI"
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Required when schedule_type=INTERVAL
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    # Fixed input fed to WorkflowRunRequest.input on every scheduled run -
    # a scheduled trigger has no human typing a message, so this must be
    # fully pre-configured.
    input_template: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    workflow: Mapped["Workflow"] = relationship()

    def __repr__(self) -> str:
        return f"<WorkflowSchedule workflow_id={self.workflow_id} type={self.schedule_type} next={self.next_run_at}>"