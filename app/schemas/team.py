from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class TeamBase(BaseModel):
    agent_os_id: UUID
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    team_prompt_id: UUID | None = None
    enabled: bool = True


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    team_prompt_id: UUID | None = None
    enabled: bool | None = None


class TeamRead(TimestampedSchema, TeamBase):
    pass
