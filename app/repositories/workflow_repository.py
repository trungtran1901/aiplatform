from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.models.workflow import Workflow, WorkflowStep
from app.repositories.base import BaseRepository


class WorkflowRepository(BaseRepository[Workflow]):
    model = Workflow

    async def get_by_code(
        self, agent_os_id: uuid.UUID, code: str, *, include_deleted: bool = False
    ) -> Workflow | None:
        stmt = select(Workflow).where(Workflow.agent_os_id == agent_os_id, Workflow.code == code)
        if not include_deleted:
            stmt = stmt.where(Workflow.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_steps(self, workflow_id: uuid.UUID) -> Workflow | None:
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.id == workflow_id, Workflow.deleted_at.is_(None))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_agent_os(self, agent_os_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, agent_os_id=agent_os_id)


class WorkflowStepRepository(BaseRepository[WorkflowStep]):
    model = WorkflowStep

    async def list_by_workflow(self, workflow_id: uuid.UUID) -> list[WorkflowStep]:
        stmt = (
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.step_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def replace_steps(self, workflow_id: uuid.UUID, steps: list[dict]) -> list[WorkflowStep]:
        """Replaces the entire ordered step sequence for a workflow.
        Steps are always replaced wholesale (never patched individually)
        so step_order is always a clean, gapless sequence reflecting
        exactly what was last submitted - matching the same
        replace-the-whole-set pattern used by capability assignments."""
        await self.session.execute(delete(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id))
        created: list[WorkflowStep] = []
        for order, step_data in enumerate(steps):
            step = WorkflowStep(workflow_id=workflow_id, step_order=order, **step_data)
            self.session.add(step)
            created.append(step)
        await self.session.flush()
        return created
