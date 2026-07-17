from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.observation import ObservationType
from app.schemas.common import TimestampedSchema


class ObservationCreate(BaseModel):
    run_id: UUID | None = None
    workflow_run_id: UUID | None = None
    agent_id: UUID | None = None
    observation_type: ObservationType
    source: str | None = None
    payload: dict = Field(default_factory=dict)
    execution_time_ms: float | None = None


class ObservationRead(TimestampedSchema):
    run_id: UUID | None
    workflow_run_id: UUID | None
    agent_id: UUID | None
    observation_type: ObservationType
    source: str | None
    payload: dict
    execution_time_ms: float | None
