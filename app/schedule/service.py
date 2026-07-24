"""
WorkflowScheduleService.

Pure metadata + next_run_at computation - contains NO polling loop and
NO execution logic (that's ticker.py and WorkflowExecutionService
respectively). Kept separate so next_run_at math is unit-testable
without spinning up any background task or Redis.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from croniter import croniter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.models.workflow_schedule import ScheduleType, WorkflowSchedule
from app.repositories.workflow_repository import WorkflowRepository
from app.repositories.workflow_schedule_repository import WorkflowScheduleRepository
from app.schemas.workflow_schedule import WorkflowScheduleCreate, WorkflowScheduleUpdate

logger = get_logger(__name__)


def compute_next_run_at(schedule: WorkflowSchedule, *, after: datetime | None = None) -> datetime:
    """Computes the next fire time strictly after `after` (default now).
    CRON uses croniter against the schedule's own timezone-naive UTC
    anchor (this platform stores all timestamps as UTC - see
    app/db/base.py - so cron_expression is interpreted in UTC unless a
    caller intentionally sets `timezone`, which is currently recorded
    but not yet used to shift the anchor; documented limitation)."""
    anchor = after or datetime.now(timezone.utc)

    if schedule.schedule_type == ScheduleType.interval:
        return anchor + timedelta(seconds=schedule.interval_seconds)

    if schedule.schedule_type == ScheduleType.cron:
        it = croniter(schedule.cron_expression, anchor)
        return it.get_next(datetime)

    raise ValidationFailedError(f"Unsupported schedule_type: {schedule.schedule_type}")


class WorkflowScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.schedule_repo = WorkflowScheduleRepository(session)
        self.workflow_repo = WorkflowRepository(session)

    async def create(self, workflow_id: uuid.UUID, payload: WorkflowScheduleCreate) -> WorkflowSchedule:
        workflow = await self.workflow_repo.get(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        if payload.schedule_type == ScheduleType.cron and not croniter.is_valid(payload.cron_expression):
            raise ValidationFailedError(f"Invalid cron_expression: {payload.cron_expression!r}")

        schedule = await self.schedule_repo.create(
            workflow_id=workflow_id,
            **payload.model_dump(),
        )
        schedule.next_run_at = compute_next_run_at(schedule)
        await self.session.flush()

        logger.info("workflow_schedule_created", schedule_id=str(schedule.id), workflow_id=str(workflow_id))
        return schedule

    async def update(self, schedule_id: uuid.UUID, payload: WorkflowScheduleUpdate) -> WorkflowSchedule:
        schedule = await self.schedule_repo.get_or_404(schedule_id)
        update_data = payload.model_dump(exclude_unset=True)
        schedule = await self.schedule_repo.update(schedule, **update_data)

        # Recompute next_run_at if timing-relevant fields changed, or if
        # re-enabling a previously-disabled schedule.
        if any(k in update_data for k in ("cron_expression", "interval_seconds", "enabled")):
            schedule.next_run_at = compute_next_run_at(schedule) if schedule.enabled else None
            await self.session.flush()

        return schedule

    async def get(self, schedule_id: uuid.UUID) -> WorkflowSchedule:
        return await self.schedule_repo.get_or_404(schedule_id)

    async def list_for_workflow(self, workflow_id: uuid.UUID, *, offset: int = 0, limit: int = 50):
        return await self.schedule_repo.list_by_workflow(workflow_id, offset=offset, limit=limit)

    async def delete(self, schedule_id: uuid.UUID) -> None:
        schedule = await self.schedule_repo.get_or_404(schedule_id)
        await self.schedule_repo.soft_delete(schedule)

    async def record_fired(
        self, schedule: WorkflowSchedule, *, status: str, workflow_run_id: uuid.UUID | None, error: str | None = None
    ) -> None:
        """Called by the ticker right after triggering a run - advances
        next_run_at and records the outcome, regardless of whether the
        triggered run itself succeeded (a failed run still needs its
        NEXT occurrence scheduled, or a bad workflow would spin forever
        on the same due timestamp)."""
        schedule.last_run_at = datetime.now(timezone.utc)
        schedule.last_status = status
        schedule.last_error = error
        schedule.last_workflow_run_id = workflow_run_id
        schedule.next_run_at = compute_next_run_at(schedule) if schedule.enabled else None
        await self.session.flush()