"""AttachmentService - upload, extract (đồng bộ ngay lúc upload), và
render text đã extract để fold vào prompt lúc chat - giống hệt vai trò
của KnowledgeSkillService nhưng cho file người dùng upload trực tiếp."""
from __future__ import annotations

import mimetypes
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.extractor import AttachmentExtractor
from app.attachments.storage_client import MinioStorageClient
from app.core.logging import get_logger
from app.models.attachment import Attachment, AttachmentKind, AttachmentStatus
from app.repositories.attachment_repository import AttachmentRepository

logger = get_logger(__name__)

_KIND_BY_MIME = {
    "image/png": AttachmentKind.image,
    "image/jpeg": AttachmentKind.image,
    "image/jpg": AttachmentKind.image,
    "application/pdf": AttachmentKind.pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": AttachmentKind.docx,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": AttachmentKind.xlsx,
}


class AttachmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AttachmentRepository(session)
        self.storage = MinioStorageClient()
        self.extractor = AttachmentExtractor()

    async def upload_and_extract(
        self, file_bytes: bytes, *, filename: str, mime_type: str,
        session_id: uuid.UUID | None = None, user_id: str | None = None,
    ) -> Attachment:
        kind = _KIND_BY_MIME.get(mime_type, AttachmentKind.other)
        storage_key = self.storage.upload(file_bytes, filename=filename, content_type=mime_type)

        attachment = await self.repo.create(
            session_id=session_id, user_id=user_id, filename=filename, mime_type=mime_type,
            kind=kind, size_bytes=len(file_bytes),
            storage_bucket=self.storage.bucket, storage_key=storage_key,
            status=AttachmentStatus.processing,
        )
        await self.session.flush()

        try:
            if kind == AttachmentKind.image:
                result = await self.extractor.extract_image(file_bytes, filename=filename, mime_type=mime_type)
            elif kind == AttachmentKind.pdf:
                result = await self.extractor.extract_pdf(file_bytes, filename=filename)
            elif kind == AttachmentKind.docx:
                result = await self.extractor.extract_docx(file_bytes, filename=filename)
            elif kind == AttachmentKind.xlsx:
                result = await self.extractor.extract_xlsx(file_bytes, filename=filename)
            else:
                result = None

            if result is None:
                attachment.status = AttachmentStatus.failed
                attachment.error_message = f"Không hỗ trợ loại file: {mime_type}"
            elif result.ok:
                attachment.status = AttachmentStatus.ready
                attachment.extracted_text = result.text
                attachment.extraction_raw = result.raw
            else:
                attachment.status = AttachmentStatus.failed
                attachment.error_message = result.error
        except Exception as exc:  # noqa: BLE001
            logger.error("attachment_extraction_unexpected_error", filename=filename, error=str(exc))
            attachment.status = AttachmentStatus.failed
            attachment.error_message = str(exc)

        await self.session.flush()
        logger.info("attachment_processed", attachment_id=str(attachment.id), status=attachment.status.value)
        return attachment

    async def render_for_prompt(self, attachment_ids: list[uuid.UUID]) -> str:
        if not attachment_ids:
            return ""
        attachments = await self.repo.get_many(attachment_ids)
        by_id = {a.id: a for a in attachments}

        sections = []
        for att_id in attachment_ids:
            attachment = by_id.get(att_id)
            if attachment is None:
                sections.append(f"[File đính kèm {att_id}: KHÔNG TỒN TẠI trong hệ thống]")
                continue
            if attachment.status != AttachmentStatus.ready or not attachment.extracted_text:
                sections.append(
                    f"[File đính kèm '{attachment.filename}': KHÔNG đọc được nội dung "
                    f"(trạng thái: {attachment.status.value}). "
                    f"TUYỆT ĐỐI KHÔNG được tự suy đoán, bịa nội dung, hoặc tìm kiếm "
                    f"tài liệu khác thay thế cho file này. Hãy báo với người dùng rằng "
                    f"file chưa xử lý được và đề nghị họ tải lại."
                )
                continue
            sections.append(f"[File đính kèm '{attachment.filename}']\n{attachment.extracted_text.strip()}")

        if not sections:
            return ""
        return (
            "=== NGỮ CẢNH FILE NGƯỜI DÙNG VỪA ĐÍNH KÈM (KHÔNG PHẢI Knowledge Base) ===\n"
            + "\n\n".join(sections)
            + "\n=== HẾT NGỮ CẢNH FILE ĐÍNH KÈM ==="
        )