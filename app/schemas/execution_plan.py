from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class PlanStepRequest(BaseModel):
    team_code: str | None = None
    agent_code: str | None = None
    input_template: str | None = None
    max_retries: int = Field(default=0, ge=0, le=5)


class ExecutionPlanRunRequest(BaseModel):
    agentOs: str
    message: str = Field(..., min_length=1)
    steps: list[PlanStepRequest] = Field(
        default_factory=list,
        description="Explicit ordered steps. If empty, falls back to a single-step plan "
        "(identical to normal /chat dispatch) even when the Planning Engine flag is on.",
    )
    session_id: UUID | None = None
    user_id: str | None = None


class ExecutionPlanRunResponse(BaseModel):
    planRunId: UUID
    status: str
    result: str | None = None
