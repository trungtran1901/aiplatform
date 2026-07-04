from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class AgentBase(BaseModel):
    team_id: UUID
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    prompt_id: UUID | None = None
    model_id: UUID | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    enabled: bool = True


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_id: UUID | None = None
    model_id: UUID | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    enabled: bool | None = None


class AgentRead(TimestampedSchema, AgentBase):
    pass
