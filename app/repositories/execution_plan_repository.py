from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.execution_plan_run import ExecutionPlanRun, ExecutionPlanStepRun
from app.repositories.base import BaseRepository


class ExecutionPlanRunRepository(BaseRepository[ExecutionPlanRun]):
    model = ExecutionPlanRun


class ExecutionPlanStepRunRepository(BaseRepository[ExecutionPlanStepRun]):
    model = ExecutionPlanStepRun

    async def list_by_plan_run(self, plan_run_id: uuid.UUID) -> list[ExecutionPlanStepRun]:
        stmt = (
            select(ExecutionPlanStepRun)
            .where(ExecutionPlanStepRun.plan_run_id == plan_run_id)
            .order_by(ExecutionPlanStepRun.step_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
