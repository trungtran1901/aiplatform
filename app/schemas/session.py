from __future__ import annotations

from uuid import UUID


from app.models.session import MessageRole
from app.schemas.common import TimestampedSchema


class ChatSessionRead(TimestampedSchema):
    agent_os_id: UUID
    team_id: UUID | None
    agent_id: UUID | None
    user_id: str | None
    title: str | None
    context: dict | None = None


class ChatMessageRead(TimestampedSchema):
    session_id: UUID
    run_id: UUID | None
    role: MessageRole
    content: str
    message_metadata: dict | None = None


class ChatSessionDetail(ChatSessionRead):
    messages: list[ChatMessageRead] = []
