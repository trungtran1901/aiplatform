from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.workflow_schedule import ScheduleType
from app.schemas.common import TimestampedSchema


class WorkflowScheduleBase(BaseModel):
    schedule_type: ScheduleType
    cron_expression: str | None = Field(default=None, description="Required when schedule_type=CRON, e.g. '0 9 * * MON-FRI'")
    interval_seconds: int | None = Field(default=None, ge=10, description="Required when schedule_type=INTERVAL")
    timezone: str = Field(default="UTC")
    input_template: str = Field(..., min_length=1, description="Fixed input fed to the workflow on every scheduled run")
    user_id: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> "WorkflowScheduleBase":
        if self.schedule_type == ScheduleType.cron and not self.cron_expression:
            raise ValueError("cron_expression is required when schedule_type=CRON")
        if self.schedule_type == ScheduleType.interval and not self.interval_seconds:
            raise ValueError("interval_seconds is required when schedule_type=INTERVAL")
        return self


class WorkflowScheduleCreate(WorkflowScheduleBase):
    pass


class WorkflowScheduleUpdate(BaseModel):
    cron_expression: str | None = None
    interval_seconds: int | None = Field(default=None, ge=10)
    timezone: str | None = None
    input_template: str | None = None
    user_id: str | None = None
    enabled: bool | None = None


class WorkflowScheduleRead(TimestampedSchema, WorkflowScheduleBase):
    workflow_id: UUID
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_workflow_run_id: UUID | None = None