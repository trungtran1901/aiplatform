from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.models.attachment import AttachmentKind, AttachmentStatus
from app.schemas.common import TimestampedSchema


class AttachmentRead(TimestampedSchema):
    session_id: UUID | None
    user_id: str | None
    filename: str
    mime_type: str
    kind: AttachmentKind
    size_bytes: int
    status: AttachmentStatus
    extracted_text: str | None = None
    error_message: str | None = None
    # storage_bucket / storage_key / extraction_raw KHÔNG expose ra API -
    # là chi tiết nội bộ, extraction_raw có thể chứa bbox/score rất dài
    # không cần thiết cho client, storage_key không nên lộ ra ngoài.


class AttachmentDownloadURL(BaseModel):
    url: str
    expires_seconds: int