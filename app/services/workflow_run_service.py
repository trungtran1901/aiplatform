"""Workflow run/event tracking service - mirrors RunTrackingService's
pattern (app/services/run_service.py) for the Workflow audit trail:
WorkflowRun, WorkflowRunStep, WorkflowEvent."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.workflow import WorkflowStep
from app.models.workflow_run import (
    WorkflowEvent,
    WorkflowEventType,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunStep,
    WorkflowStepStatus,
)
from app.repositories.workflow_run_repository import (
    WorkflowEventRepository,
    WorkflowRunRepository,
    WorkflowRunStepRepository,
)

logger = get_logger(__name__)


class WorkflowRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repo = WorkflowRunRepository(session)
        self.run_step_repo = WorkflowRunStepRepository(session)
        self.event_repo = WorkflowEventRepository(session)

    async def create_run(
        self,
        workflow_id: uuid.UUID,
        session_id: uuid.UUID,
        input_text: str,
        *,
        created_by: str | None = None,
    ) -> WorkflowRun:
        run = await self.run_repo.create(
            workflow_id=workflow_id,
            session_id=session_id,
            status=WorkflowRunStatus.pending,
            input=input_text,
            created_by=created_by,
        )
        await self.emit_event(run.id, WorkflowEventType.workflow_started, {"input": input_text})
        return run

    async def mark_running(self, run: WorkflowRun) -> WorkflowRun:
        run.status = WorkflowRunStatus.running
        run.started_at = datetime.now(timezone.utc)
        await self.session.flush()
        return run

    async def mark_completed(self, run: WorkflowRun, result: str) -> WorkflowRun:
        run.status = WorkflowRunStatus.completed
        run.result = result
        run.completed_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.emit_event(run.id, WorkflowEventType.workflow_completed, {"result_length": len(result)})
        return run

    async def mark_failed(self, run: WorkflowRun, error_message: str) -> WorkflowRun:
        run.status = WorkflowRunStatus.failed
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.emit_event(run.id, WorkflowEventType.workflow_failed, {"error": error_message})
        return run

    async def start_step(self, workflow_run_id: uuid.UUID, step: WorkflowStep, step_input: str) -> WorkflowRunStep:
        run_step = await self.run_step_repo.create(
            workflow_run_id=workflow_run_id,
            workflow_step_id=step.id,
            step_order=step.step_order,
            status=WorkflowStepStatus.running,
            started_at=datetime.now(timezone.utc),
            input={"text": step_input},
        )
        await self.emit_event(
            workflow_run_id,
            WorkflowEventType.workflow_step_started,
            {"step_order": step.step_order, "step_type": step.step_type.value},
        )
        return run_step

    async def complete_step(self, run_step: WorkflowRunStep, output: str) -> WorkflowRunStep:
        run_step.status = WorkflowStepStatus.completed
        run_step.output = {"text": output}
        run_step.completed_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.emit_event(
            run_step.workflow_run_id,
            WorkflowEventType.workflow_step_completed,
            {"step_order": run_step.step_order},
        )
        return run_step

    async def fail_step(self, run_step: WorkflowRunStep, error_message: str) -> WorkflowRunStep:
        run_step.status = WorkflowStepStatus.failed
        run_step.error_message = error_message
        run_step.completed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return run_step

    async def emit_event(
        self, workflow_run_id: uuid.UUID, event_type: WorkflowEventType, payload: dict
    ) -> WorkflowEvent:
        event = await self.event_repo.create(
            workflow_run_id=workflow_run_id, event_type=event_type, payload=payload
        )
        logger.info("workflow_event_emitted", workflow_run_id=str(workflow_run_id), event_type=event_type.value)
        return event

    async def list_steps(self, workflow_run_id: uuid.UUID) -> list[WorkflowRunStep]:
        return await self.run_step_repo.list_by_run(workflow_run_id)

    async def list_events(self, workflow_run_id: uuid.UUID) -> list[WorkflowEvent]:
        return await self.event_repo.list_by_run(workflow_run_id)
