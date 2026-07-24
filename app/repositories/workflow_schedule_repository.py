from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.workflow_schedule import WorkflowSchedule
from app.repositories.base import BaseRepository


class WorkflowScheduleRepository(BaseRepository[WorkflowSchedule]):
    model = WorkflowSchedule

    async def list_by_workflow(self, workflow_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, workflow_id=workflow_id)

    async def list_due(self, *, as_of: datetime, limit: int = 100) -> list[WorkflowSchedule]:
        """Every enabled, non-deleted schedule whose next_run_at has
        arrived - the query the ticker polls on every tick."""
        stmt = (
            select(WorkflowSchedule)
            .where(
                WorkflowSchedule.deleted_at.is_(None),
                WorkflowSchedule.enabled.is_(True),
                WorkflowSchedule.next_run_at.is_not(None),
                WorkflowSchedule.next_run_at <= as_of,
            )
            .order_by(WorkflowSchedule.next_run_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())