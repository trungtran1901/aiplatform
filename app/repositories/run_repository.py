from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.run import AgentEvent, AgentRun
from app.repositories.base import BaseRepository


class AgentRunRepository(BaseRepository[AgentRun]):
    model = AgentRun

    async def list_by_session(self, session_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, session_id=session_id)


class AgentEventRepository(BaseRepository[AgentEvent]):
    model = AgentEvent

    async def list_by_run(self, run_id: uuid.UUID) -> list[AgentEvent]:
        stmt = (
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id)
            .order_by(AgentEvent.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
