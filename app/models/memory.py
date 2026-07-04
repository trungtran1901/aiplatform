"""Memory management: agent_memories.

Where possible the runtime delegates to Agno's own memory subsystem
(agno.memory.v2.Memory, enabled per-agent via enable_user_memories) for
the actual fact/preference EXTRACTION - Agno calls an LLM after each run
to decide what's worth remembering, exactly like ChatGPT-style memory.
This table is the durable, queryable record used by the platform's own
APIs (GET /api/v1/memories, etc.) and persists across process restarts -
chat_service.py syncs newly-created Agno UserMemory entries into this
table after each run (see app/services/chat_service.py and
app/services/memory_service.py).
"""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MemoryType(str, Enum):
    conversation = "conversation"
    summary = "summary"
    fact = "fact"
    preference = "preference"
    working_memory = "working_memory"


class AgentMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "user_id", "source_memory_id", name="uq_agent_memory_source"
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    memory_type: Mapped[MemoryType] = mapped_column(
        SAEnum(MemoryType, name="memory_type"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(nullable=False)

    # Agno's own memory_id (agno.memory.v2.schema.UserMemory.memory_id),
    # used to detect which Agno-extracted memories have already been
    # synced into this table, so re-syncing after later runs doesn't
    # create duplicate rows for the same underlying memory. NULL for
    # memories created directly via the API rather than by Agno.
    source_memory_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    agent: Mapped["Agent"] = relationship()

    def __repr__(self) -> str:
        return f"<AgentMemory type={self.memory_type} agent_id={self.agent_id}>"