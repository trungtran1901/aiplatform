from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.observation import RuntimeObservation
from app.repositories.base import BaseRepository


class ObservationRepository(BaseRepository[RuntimeObservation]):
    model = RuntimeObservation

    async def list_by_run(self, run_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, run_id=run_id)

    async def list_by_workflow_run(self, workflow_run_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, workflow_run_id=workflow_run_id)
