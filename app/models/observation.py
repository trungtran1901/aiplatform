"""Observation Engine - AgentX Runtime v2 (Phase 6, flagged).

Structured, queryable observations collected during execution (Knowledge
retrieval, Skill outputs, business responses, UI results, warnings,
errors, execution time) - append-only, same audit philosophy as
agent_events/workflow_events, but deliberately a separate table since
observations are cross-cutting (not scoped to exactly one AgentRun or
WorkflowRun) and are meant to become runtime memory a Context Engine can
read back later, not just an audit trail.
"""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ObservationType(str, Enum):
    knowledge_retrieval = "KNOWLEDGE_RETRIEVAL"
    skill_output = "SKILL_OUTPUT"
    business_response = "BUSINESS_RESPONSE"
    ui_result = "UI_RESULT"
    warning = "WARNING"
    error = "ERROR"


class RuntimeObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runtime_observations"

    # Loosely-scoped: any of these may be null depending on what produced
    # the observation (a chat run, a workflow run, an ad-hoc execution
    # plan step) - no FK constraint, since observations must never be
    # blocked by, or cascade-delete, whichever run produced them.
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    observation_type: Mapped[ObservationType] = mapped_column(
        SAEnum(ObservationType, name="observation_type", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    execution_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<RuntimeObservation type={self.observation_type} run_id={self.run_id}>"
