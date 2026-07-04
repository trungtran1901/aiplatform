from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.workflow_run import WorkflowEvent, WorkflowRun, WorkflowRunStep
from app.repositories.base import BaseRepository


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    model = WorkflowRun

    async def list_by_workflow(self, workflow_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, workflow_id=workflow_id)


class WorkflowRunStepRepository(BaseRepository[WorkflowRunStep]):
    model = WorkflowRunStep

    async def list_by_run(self, workflow_run_id: uuid.UUID) -> list[WorkflowRunStep]:
        stmt = (
            select(WorkflowRunStep)
            .where(WorkflowRunStep.workflow_run_id == workflow_run_id)
            .order_by(WorkflowRunStep.step_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class WorkflowEventRepository(BaseRepository[WorkflowEvent]):
    model = WorkflowEvent

    async def list_by_run(self, workflow_run_id: uuid.UUID) -> list[WorkflowEvent]:
        stmt = (
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_run_id == workflow_run_id)
            .order_by(WorkflowEvent.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
