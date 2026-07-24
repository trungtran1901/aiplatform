from __future__ import annotations

import uuid

from app.models.attachment import Attachment, AttachmentStatus
from app.repositories.base import BaseRepository


class AttachmentRepository(BaseRepository[Attachment]):
    model = Attachment

    async def list_by_session(self, session_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, session_id=session_id)

    async def list_by_user(self, user_id: str, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, user_id=user_id)

    async def get_many(self, attachment_ids: list[uuid.UUID]) -> list[Attachment]:
        """Batch fetch nhiều attachment cùng lúc - dùng trong
        AttachmentService.render_for_prompt để tránh N query riêng lẻ
        khi một lượt chat đính kèm nhiều file."""
        if not attachment_ids:
            return []
        from sqlalchemy import select

        stmt = select(Attachment).where(Attachment.id.in_(attachment_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())