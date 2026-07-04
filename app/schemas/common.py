"""Common response envelopes and shared schema utilities."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMBase(BaseModel):
    """Base for schemas that read directly from SQLAlchemy ORM instances."""

    model_config = ConfigDict(from_attributes=True)


class TimestampedSchema(ORMBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict = {}
    correlation_id: str | None = None
