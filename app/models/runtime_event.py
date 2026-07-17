"""Event Engine - AgentX Runtime v2 (Phase 7, flagged).

Generic, UI-facing runtime events (Page Opened, Dialog Opened, Field
Changed, Workflow Started/Completed, Skill Completed, Knowledge
Retrieved, ...) - distinct from agent_events/workflow_events, which are
scoped strictly to one AgentRun/WorkflowRun's own execution timeline.
RuntimeEvent is entity-agnostic (entity_type/entity_id) so a UI
application can emit its own client-side events (e.g. "Page Opened")
into the same stream a chat run's events flow through, giving a future
UI a single unified timeline. Append-only, SSE-streamable via the same
polling pattern as GET /runs/{id}/stream (app/api/v1/runs.py).
"""
from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RuntimeEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runtime_events"

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<RuntimeEvent {self.entity_type}:{self.entity_id} event={self.event_name}>"
