from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.ui_metadata import UIMetadataKind
from app.schemas.common import TimestampedSchema


class UIMetadataBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_.]*$")
    kind: UIMetadataKind
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    parent_code: str | None = Field(
        default=None, description="Code of the parent artifact, e.g. a Form's parent Page"
    )
    payload: dict = Field(..., description="Kind-specific metadata payload (fields, validation, lookups, etc.)")
    schema_version: str = Field(default="1.0")
    enabled: bool = True


class UIMetadataCreate(UIMetadataBase):
    """version is server-assigned (auto-incremented per code+kind),
    same pattern as PromptCreate - callers never set it directly."""


class UIMetadataUpdate(BaseModel):
    """Updating creates a NEW version rather than mutating history in
    place - same immutable-version philosophy as Prompt. Only the
    fields that make sense to bump together are here; code/kind are
    immutable once created."""

    name: str | None = None
    description: str | None = None
    parent_code: str | None = None
    payload: dict | None = None
    schema_version: str | None = None
    enabled: bool | None = None


class UIMetadataRead(TimestampedSchema, UIMetadataBase):
    version: int
