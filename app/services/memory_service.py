"""
Memory management service.

Two layers, deliberately not unified into one hidden store:

  - Agno's own agentic memory (agno.memory.v2.Memory + MemoryManager,
    enabled per-agent via enable_user_memories=True in engine.py) does
    the actual EXTRACTION: after each run, it calls an LLM to decide
    what facts/preferences from the conversation are worth remembering,
    exactly like ChatGPT-style memory - no hand-written extraction
    logic lives in this codebase.
  - `agent_memories` (this platform's own table) is the durable,
    queryable record exposed by GET /api/v1/memories,
    GET /api/v1/agents/{id}/memories, and DELETE /api/v1/memories/{id}.

`sync_from_agno()` is the bridge: chat_service.py calls it after every
run that had a user_id, handing it whatever agno.memory.v2.schema.
UserMemory entries Agno's MemoryManager produced for that user. Each one
is upserted by its Agno-native `memory_id` so re-syncing after later
runs never creates duplicate rows for the same underlying memory.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.memory import AgentMemory, MemoryType
from app.repositories.memory_repository import AgentMemoryRepository

logger = get_logger(__name__)


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.memory_repo = AgentMemoryRepository(session)

    async def record(
        self,
        agent_id: uuid.UUID,
        *,
        user_id: str | None,
        memory_type: MemoryType,
        content: str,
        source_memory_id: str | None = None,
    ) -> AgentMemory:
        memory = await self.memory_repo.create(
            agent_id=agent_id,
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            source_memory_id=source_memory_id,
        )
        logger.info("memory_recorded", agent_id=str(agent_id), memory_type=memory_type.value)
        return memory

    async def sync_from_agno(
        self,
        agent_id: uuid.UUID,
        user_id: str,
        agno_user_memories: list[Any],
    ) -> list[AgentMemory]:
        """Upserts Agno-extracted UserMemory entries into agent_memories.

        `agno_user_memories` is the list returned by
        `agno_agent.memory.get_user_memories(user_id=...)` after a run -
        each item exposes `.memory_id` and `.memory` (the extracted text).
        Entries whose memory_id already exists for this
        (agent_id, user_id) are skipped (Agno reuses the same memory_id
        when it updates rather than duplicates an existing memory, but we
        still guard here defensively); new ones are inserted as
        memory_type=fact, which is the closest fit for free-form
        LLM-extracted facts/preferences.
        """
        synced: list[AgentMemory] = []
        for um in agno_user_memories:
            source_id = getattr(um, "memory_id", None)
            content = getattr(um, "memory", None)
            if not content:
                continue

            if source_id:
                existing = await self.memory_repo.get_by_source_memory_id(agent_id, user_id, source_id)
                if existing is not None:
                    if existing.content != content:
                        existing.content = content
                        await self.session.flush()
                    synced.append(existing)
                    continue

            created = await self.record(
                agent_id,
                user_id=user_id,
                memory_type=MemoryType.fact,
                content=content,
                source_memory_id=source_id,
            )
            synced.append(created)

        if synced:
            logger.info(
                "memories_synced_from_agno",
                agent_id=str(agent_id),
                user_id=user_id,
                count=len(synced),
            )
        return synced

    async def list_for_agent(self, agent_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.memory_repo.list_by_agent(agent_id, offset=offset, limit=limit)

    async def delete(self, memory_id: uuid.UUID) -> None:
        memory = await self.memory_repo.get_or_404(memory_id)
        await self.memory_repo.hard_delete(memory)