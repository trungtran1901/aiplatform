"""
ObservationEngineService.

Thin recording layer over RuntimeObservation - no orchestration logic,
mirrors RunTrackingService.emit_event's simplicity (app/services/run_service.py).
Disabled by default: record() becomes a no-op (returns None) when
FEATURE_OBSERVATION_ENGINE is off, so callers can always call it
unconditionally without checking the flag themselves - same
safe-by-default pattern as ContextEngineService.build_context_block().
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.observation import ObservationType, RuntimeObservation
from app.repositories.observation_repository import ObservationRepository

logger = get_logger(__name__)


class ObservationEngineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ObservationRepository(session)

    async def record(
        self,
        observation_type: ObservationType,
        payload: dict,
        *,
        run_id: uuid.UUID | None = None,
        workflow_run_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        source: str | None = None,
        execution_time_ms: float | None = None,
    ) -> RuntimeObservation | None:
        if not get_settings().FEATURE_OBSERVATION_ENGINE:
            return None

        observation = await self.repo.create(
            run_id=run_id,
            workflow_run_id=workflow_run_id,
            agent_id=agent_id,
            observation_type=observation_type,
            source=source,
            payload=payload,
            execution_time_ms=execution_time_ms,
        )
        logger.info("observation_recorded", observation_type=observation_type.value, source=source)
        return observation

    async def list_for_run(self, run_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.repo.list_by_run(run_id, offset=offset, limit=limit)

    async def list_for_workflow_run(self, workflow_run_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.repo.list_by_workflow_run(workflow_run_id, offset=offset, limit=limit)
