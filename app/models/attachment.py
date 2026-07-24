"""Attachment Registry - lưu file upload + kết quả extract text (OCR/parse),
để không phải gọi lại OCR service mỗi lần agent cần đọc file trong context."""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AttachmentStatus(str, Enum):
    uploaded = "UPLOADED"       # file đã lên MinIO, chưa extract
    processing = "PROCESSING"   # đang gọi OCR/parser
    ready = "READY"             # đã có extracted_text, sẵn sàng dùng
    failed = "FAILED"           # extract lỗi


class AttachmentKind(str, Enum):
    image = "IMAGE"
    pdf = "PDF"
    docx = "DOCX"
    xlsx = "XLSX"
    other = "OTHER"


class Attachment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachments"

    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[AttachmentKind] = mapped_column(
        SAEnum(AttachmentKind, name="attachment_kind", values_callable=lambda o: [e.value for e in o]),
        nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # MinIO object key (không lưu presigned URL - tạo lúc cần)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)

    status: Mapped[AttachmentStatus] = mapped_column(
        SAEnum(AttachmentStatus, name="attachment_status", values_callable=lambda o: [e.value for e in o]),
        default=AttachmentStatus.uploaded, nullable=False, index=True,
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # raw OCR json (bbox, score...) để debug/trích dẫn vị trí sau này
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} filename={self.filename} status={self.status}>"