from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.memory import AgentMemory
from app.repositories.base import BaseRepository


class AgentMemoryRepository(BaseRepository[AgentMemory]):
    model = AgentMemory

    async def list_by_agent(self, agent_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, agent_id=agent_id)

    async def get_by_source_memory_id(
        self, agent_id: uuid.UUID, user_id: str | None, source_memory_id: str
    ) -> AgentMemory | None:
        """Looks up a previously-synced Agno memory by its native
        memory_id, used to avoid creating duplicate rows when re-syncing
        after later runs."""
        stmt = select(AgentMemory).where(
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id == user_id,
            AgentMemory.source_memory_id == source_memory_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()