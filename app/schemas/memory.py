from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.models.memory import MemoryType
from app.schemas.common import TimestampedSchema


class AgentMemoryCreate(BaseModel):
    agent_id: UUID
    user_id: str | None = None
    memory_type: MemoryType
    content: str = Field(..., min_length=1)


class AgentMemoryRead(TimestampedSchema):
    agent_id: UUID
    user_id: str | None
    memory_type: MemoryType
    content: str
    source_memory_id: str | None = None