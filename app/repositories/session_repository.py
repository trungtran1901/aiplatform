from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.session import ChatMessage, ChatSession
from app.repositories.base import BaseRepository


class ChatSessionRepository(BaseRepository[ChatSession]):
    model = ChatSession

    async def get_with_messages(
        self, session_id: uuid.UUID, *, user_id: str | None = None
    ) -> ChatSession | None:
        from sqlalchemy.orm import selectinload

        stmt = (
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id, ChatSession.deleted_at.is_(None))
        )
        if user_id is not None:
            stmt = stmt.where(ChatSession.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ChatMessageRepository(BaseRepository[ChatMessage]):
    model = ChatMessage

    async def list_by_session(self, session_id: uuid.UUID) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())