from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.prompt import PromptStatus
from app.schemas.common import TimestampedSchema


class PromptBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    version: int = Field(default=1, ge=1)
    status: PromptStatus = PromptStatus.draft


class PromptCreate(PromptBase):
    pass


class PromptUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    status: PromptStatus | None = None


class PromptRead(TimestampedSchema, PromptBase):
    pass
