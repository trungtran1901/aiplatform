from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class SkillBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    instructions: str | None = None


class SkillCreate(SkillBase):
    capability_codes: list[str] = Field(default_factory=list)


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    capability_codes: list[str] | None = None


class SkillRead(TimestampedSchema, SkillBase):
    capability_codes: list[str] = Field(default_factory=list)


class AgentSkillAssign(BaseModel):
    agent_id: UUID
    skill_id: UUID
