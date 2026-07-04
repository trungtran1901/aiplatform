"""Workflow registry: Workflow (Layer 4 of the AgentOS hierarchy, sibling
to Teams) and WorkflowStep (an ordered AGENT or TEAM execution step
within a Workflow).

Workflows are metadata-driven like everything else in the platform: no
workflow is ever hardcoded in code. Each WorkflowStep references exactly
one Agent OR exactly one Team (never both) by id, resolved at execution
time by WorkflowExecutor (see app/agno_runtime/workflow_engine.py),
which reuses AgnoRuntimeEngine's existing Agent/Team execution - it does
not duplicate any LLM/tool-calling logic.
"""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CodeMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowStepType(str, Enum):
    agent = "AGENT"
    team = "TEAM"


class Workflow(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A named, ordered sequence of AGENT/TEAM steps. Sequential only -
    Phase 1 deliberately has no branching, loops, parallel execution, or
    approval steps (those belong to MCP Gateway / n8n / a future BPM
    layer, never to this runtime)."""

    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("agent_os_id", "code", name="uq_workflow_agent_os_code"),)

    agent_os_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_os.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional default team scope for steps that don't carry their own
    # team_id explicitly (kept per spec's `workflows.team_id` field).
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    workflow_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    agent_os: Mapped["AgentOS"] = relationship()
    team: Mapped["Team"] = relationship(foreign_keys=[team_id])
    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowStep.step_order"
    )

    def __repr__(self) -> str:
        return f"<Workflow code={self.code} agent_os_id={self.agent_os_id}>"


class WorkflowStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One ordered step in a Workflow. Exactly one of agent_id / team_id
    must be set, matching step_type - enforced in the application layer
    (app/services/workflow_service.py), not as a DB CHECK constraint, to
    keep cross-dialect portability of the hand-authored migrations
    simple (see existing migrations' approach)."""

    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("workflow_id", "step_order", name="uq_workflow_step_order"),)

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[WorkflowStepType] = mapped_column(
        SAEnum(
        WorkflowStepType,
        name="workflow_step_type",
        values_callable=lambda obj: [e.value for e in obj],
    ),
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    step_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    workflow: Mapped["Workflow"] = relationship(back_populates="steps")
    agent: Mapped["Agent"] = relationship(foreign_keys=[agent_id])
    team: Mapped["Team"] = relationship(foreign_keys=[team_id])

    def __repr__(self) -> str:
        return f"<WorkflowStep workflow_id={self.workflow_id} order={self.step_order} type={self.step_type}>"
