from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.attachments.service import AttachmentService
from app.schemas.attachment import AttachmentRead

router = APIRouter(prefix="/attachments", tags=["Attachments"])


@router.post("/upload", response_model=AttachmentRead)
async def upload_attachment(
    file: UploadFile = File(...),
    session_id: UUID | None = Form(default=None),
    user_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Upload file (ảnh/pdf/docx/xlsx), lưu vào MinIO, và extract text
    ngay lập tức (OCR cho ảnh/pdf, parser cho docx/xlsx). Trả về
    attachment với extracted_text sẵn sàng để dùng trong `uiContext.attachments`
    của request /chat."""
    file_bytes = await file.read()
    service = AttachmentService(db)
    attachment = await service.upload_and_extract(
        file_bytes, filename=file.filename, mime_type=file.content_type,
        session_id=session_id, user_id=user_id,
    )
    return AttachmentRead.model_validate(attachment)