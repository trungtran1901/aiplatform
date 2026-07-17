from __future__ import annotations

from sqlalchemy import select

from app.models.runtime_event import RuntimeEvent
from app.repositories.base import BaseRepository


class RuntimeEventRepository(BaseRepository[RuntimeEvent]):
    model = RuntimeEvent

    async def list_by_entity(self, entity_type: str, entity_id: str, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, entity_type=entity_type, entity_id=entity_id)

    async def list_since(self, entity_type: str, entity_id: str, *, since_id_str: str | None = None, limit: int = 100):
        """Used by the SSE tail endpoint - returns events for an entity,
        optionally excluding everything up to and including a
        previously-seen id (caller tracks `seen_ids` client-side, same
        pattern as GET /runs/{id}/stream)."""
        stmt = (
            select(RuntimeEvent)
            .where(RuntimeEvent.entity_type == entity_type, RuntimeEvent.entity_id == entity_id)
            .order_by(RuntimeEvent.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
