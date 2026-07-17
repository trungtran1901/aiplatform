from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class RuntimeEventCreate(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=64, description="e.g. 'page', 'workflow_run', 'agent_run'")
    entity_id: str = Field(..., min_length=1, max_length=128)
    event_name: str = Field(..., min_length=1, max_length=128, description="e.g. 'PageOpened', 'FieldChanged'")
    payload: dict = Field(default_factory=dict)
    correlation_id: str | None = None


class RuntimeEventRead(TimestampedSchema):
    entity_type: str
    entity_id: str
    event_name: str
    payload: dict
    correlation_id: str | None
