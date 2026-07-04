from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.workflow import WorkflowStepType
from app.schemas.common import TimestampedSchema


class WorkflowStepDefinition(BaseModel):
    """One step in a workflow definition, addressed by code (human-facing
    create/update payloads use agentCode/teamCode, matching the spec's
    JSON example) - resolved to agent_id/team_id server-side against the
    Workflow's own agent_os_id, since codes are only unique within a
    given AgentOS/Team scope, not globally."""

    type: WorkflowStepType
    agentCode: str | None = Field(default=None, description="Required when type=AGENT")
    teamCode: str | None = Field(default=None, description="Required when type=TEAM")
    config: dict | None = Field(default=None, description="Arbitrary per-step configuration")

    @model_validator(mode="after")
    def _validate_code_matches_type(self) -> "WorkflowStepDefinition":
        if self.type == WorkflowStepType.agent and not self.agentCode:
            raise ValueError("agentCode is required when type=AGENT")
        if self.type == WorkflowStepType.team and not self.teamCode:
            raise ValueError("teamCode is required when type=TEAM")
        return self


class WorkflowStepRead(TimestampedSchema):
    workflow_id: UUID
    step_order: int
    step_type: WorkflowStepType
    agent_id: UUID | None
    team_id: UUID | None
    step_config: dict | None = None


class WorkflowBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    team_id: UUID | None = Field(
        default=None, description="Optional default team scope, per the spec's workflows.team_id field"
    )
    enabled: bool = True
    workflow_metadata: dict | None = None


class WorkflowCreate(WorkflowBase):
    agent_os_id: UUID
    steps: list[WorkflowStepDefinition] = Field(..., min_length=1)
    created_by: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    team_id: UUID | None = None
    enabled: bool | None = None
    workflow_metadata: dict | None = None
    steps: list[WorkflowStepDefinition] | None = Field(
        default=None, description="If provided, replaces the entire step sequence"
    )


class WorkflowRead(TimestampedSchema, WorkflowBase):
    agent_os_id: UUID
    created_by: str | None = None


class WorkflowDetail(WorkflowRead):
    steps: list[WorkflowStepRead] = Field(default_factory=list)
