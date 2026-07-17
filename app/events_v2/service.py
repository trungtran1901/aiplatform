"""
EventEngineService.

emit() is a safe no-op (returns None) when FEATURE_EVENT_ENGINE is off -
same always-callable pattern as ObservationEngineService.record() and
ContextEngineService.build_context_block(), so wiring a call to this
into an existing code path is never a behavior change until the flag is
turned on.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.runtime_event import RuntimeEvent
from app.repositories.runtime_event_repository import RuntimeEventRepository

logger = get_logger(__name__)


class EventEngineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RuntimeEventRepository(session)

    async def emit(
        self,
        entity_type: str,
        entity_id: str,
        event_name: str,
        payload: dict | None = None,
        *,
        correlation_id: str | None = None,
    ) -> RuntimeEvent | None:
        if not get_settings().FEATURE_EVENT_ENGINE:
            return None

        event = await self.repo.create(
            entity_type=entity_type,
            entity_id=entity_id,
            event_name=event_name,
            payload=payload or {},
            correlation_id=correlation_id,
        )
        logger.info("runtime_event_emitted", entity_type=entity_type, entity_id=entity_id, event_name=event_name)
        return event

    async def list_for_entity(self, entity_type: str, entity_id: str, *, offset: int = 0, limit: int = 50):
        return await self.repo.list_by_entity(entity_type, entity_id, offset=offset, limit=limit)
