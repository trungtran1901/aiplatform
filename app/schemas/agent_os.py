from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class AgentOSBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    default_model_id: UUID | None = None
    shared_prompt_id: UUID | None = None
    enabled: bool = True


class AgentOSCreate(AgentOSBase):
    pass


class AgentOSUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_model_id: UUID | None = None
    shared_prompt_id: UUID | None = None
    enabled: bool | None = None


class AgentOSRead(TimestampedSchema, AgentOSBase):
    deleted_at: None | str = None
