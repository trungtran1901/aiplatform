from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.workflow_run import WorkflowEventType, WorkflowRunStatus, WorkflowStepStatus
from app.schemas.common import TimestampedSchema


class WorkflowRunRequest(BaseModel):
    """POST /api/v1/workflows/{id}/run request body, per spec:
    {"input": "Analyze HR leave policy"}"""

    input: str = Field(..., min_length=1)
    session_id: UUID | None = Field(
        default=None, description="Optional existing session to run the workflow within"
    )
    user_id: str | None = None


class WorkflowRunResponse(BaseModel):
    """Per spec: {"workflowRunId": "", "status": "COMPLETED", "result": "..."}"""

    workflowRunId: UUID
    status: WorkflowRunStatus
    result: str | None = None


class WorkflowRunRead(TimestampedSchema):
    workflow_id: UUID
    session_id: UUID
    status: WorkflowRunStatus
    input: str
    result: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str | None


class WorkflowRunStepRead(TimestampedSchema):
    workflow_run_id: UUID
    workflow_step_id: UUID
    step_order: int
    status: WorkflowStepStatus
    started_at: datetime | None
    completed_at: datetime | None
    input: dict | None
    output: dict | None
    error_message: str | None


class WorkflowEventRead(TimestampedSchema):
    workflow_run_id: UUID
    event_type: WorkflowEventType
    payload: dict | None = None
