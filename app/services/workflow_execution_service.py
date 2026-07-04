"""
WorkflowExecutionService.

Top-level orchestration for executing a Workflow end to end - mirrors
ChatService's pattern (app/services/chat_service.py) at the Workflow
level: resolve metadata, get-or-create a session, create the run record,
drive WorkflowExecutor through every step, persist WorkflowRunStep +
WorkflowEvent rows as they occur, mark the run completed/failed.
"""
from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agno_runtime.engine import AgnoRuntimeEngine
from app.agno_runtime.workflow_context import WorkflowContext
from app.agno_runtime.workflow_executor import WorkflowExecutor
from app.agno_runtime.workflow_runner import WorkflowRunner
from app.core.exceptions import NotFoundError, RuntimeExecutionError
from app.core.logging import get_logger
from app.models.session import MessageRole
from app.repositories.session_repository import ChatMessageRepository, ChatSessionRepository
from app.repositories.workflow_repository import WorkflowRepository, WorkflowStepRepository
from app.schemas.workflow_run import WorkflowRunRequest
from app.services.workflow_run_service import WorkflowRunService

logger = get_logger(__name__)


class WorkflowExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workflow_repo = WorkflowRepository(session)
        self.step_repo = WorkflowStepRepository(session)
        self.session_repo = ChatSessionRepository(session)
        self.message_repo = ChatMessageRepository(session)
        self.run_service = WorkflowRunService(session)
        self.engine = AgnoRuntimeEngine(session)
        self.runner = WorkflowRunner(self.engine)
        self.executor = WorkflowExecutor(self.runner)

    async def _get_or_create_session(self, workflow_id: uuid.UUID, request: WorkflowRunRequest):
        """Reuses chat_sessions as the Workflow's session too, so a
        Workflow run and any agent chat turn that happens to use the
        same session_id share Agno's session-scoped memory/history -
        same ownership semantics as ChatService._get_or_create_session
        (see app/services/chat_service.py): a client-supplied session_id
        that doesn't exist yet is created with exactly that id; one that
        exists is only reused if its user_id matches.
        """
        workflow = await self.workflow_repo.get_or_404(workflow_id)

        if request.session_id:
            existing = await self.session_repo.get(request.session_id)
            if existing is not None:
                if existing.user_id != request.user_id:
                    raise NotFoundError(f"ChatSession {request.session_id} not found for this user_id")
                return existing
            return await self.session_repo.create(
                id=request.session_id,
                agent_os_id=workflow.agent_os_id,
                team_id=workflow.team_id,
                agent_id=None,
                user_id=request.user_id,
                title=f"Workflow: {workflow.name}",
            )

        return await self.session_repo.create(
            agent_os_id=workflow.agent_os_id,
            team_id=workflow.team_id,
            agent_id=None,
            user_id=request.user_id,
            title=f"Workflow: {workflow.name}",
        )

    async def run_workflow(self, workflow_id: uuid.UUID, request: WorkflowRunRequest) -> dict[str, Any]:
        """Non-streaming workflow execution. Used by POST /api/v1/workflows/{id}/run."""
        workflow = await self.workflow_repo.get_or_404(workflow_id)
        if not workflow.enabled:
            raise RuntimeExecutionError(f"Workflow {workflow_id} is disabled")

        steps = await self.step_repo.list_by_workflow(workflow_id)
        if not steps:
            raise RuntimeExecutionError(f"Workflow {workflow_id} has no steps configured")

        chat_session = await self._get_or_create_session(workflow_id, request)

        run = await self.run_service.create_run(
            workflow_id, chat_session.id, request.input, created_by=request.user_id
        )
        await self.message_repo.create(
            session_id=chat_session.id, run_id=None, role=MessageRole.user, content=request.input
        )
        await self.run_service.mark_running(run)

        context = WorkflowContext(
            workflowRunId=run.id,
            workflowId=workflow.id,
            sessionId=chat_session.id,
            userId=request.user_id,
        )

        # Tracks the in-flight WorkflowRunStep record for whichever step
        # is currently executing, so on_step_completed/on_step_failed can
        # finalize the SAME record on_step_started just created -
        # avoiding the earlier bug where every step's record was created
        # up front and a later failure incorrectly marked already-
        # completed steps as failed too.
        current_record: dict[str, Any] = {}

        async def on_step_started(step, step_input):
            current_record["record"] = await self.run_service.start_step(run.id, step, step_input)

        async def on_step_completed(step, output):
            await self.run_service.complete_step(current_record["record"], output)

        async def on_step_failed(step, error_message):
            await self.run_service.fail_step(current_record["record"], error_message)

        try:
            result = await self.executor.execute(
                steps,
                request.input,
                context,
                on_step_started=on_step_started,
                on_step_completed=on_step_completed,
                on_step_failed=on_step_failed,
            )
        except RuntimeExecutionError as exc:
            await self.run_service.mark_failed(run, str(exc))
            raise

        await self.message_repo.create(
            session_id=chat_session.id, run_id=None, role=MessageRole.assistant, content=result
        )
        await self.run_service.mark_completed(run, result)

        return {"workflowRunId": run.id, "status": run.status.value, "result": result}

    async def run_workflow_stream(
        self, workflow_id: uuid.UUID, request: WorkflowRunRequest
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming workflow execution via SSE. Yields workflow-level
        markers (WorkflowStarted/WorkflowStepStarted/.../WorkflowCompleted/
        WorkflowFailed) interleaved with the underlying Agent/Team
        run_stream events for whichever step is currently executing."""
        workflow = await self.workflow_repo.get_or_404(workflow_id)
        if not workflow.enabled:
            raise RuntimeExecutionError(f"Workflow {workflow_id} is disabled")

        steps = await self.step_repo.list_by_workflow(workflow_id)
        if not steps:
            raise RuntimeExecutionError(f"Workflow {workflow_id} has no steps configured")

        chat_session = await self._get_or_create_session(workflow_id, request)
        run = await self.run_service.create_run(
            workflow_id, chat_session.id, request.input, created_by=request.user_id
        )
        await self.message_repo.create(
            session_id=chat_session.id, run_id=None, role=MessageRole.user, content=request.input
        )
        await self.session.commit()
        await self.run_service.mark_running(run)
        await self.session.commit()

        context = WorkflowContext(
            workflowRunId=run.id,
            workflowId=workflow.id,
            sessionId=chat_session.id,
            userId=request.user_id,
        )

        yield {"event_type": "WorkflowStarted", "workflow_run_id": run.id, "data": {"input": request.input}}

        current_run_step = None
        try:
            async for item in self.executor.execute_stream(steps, request.input, context):
                marker = item["marker"]
                step = item["step"]

                if marker == "workflow_step_started":
                    current_run_step = await self.run_service.start_step(run.id, step, item["step_input"])
                    await self.session.commit()
                    yield {
                        "event_type": "WorkflowStepStarted",
                        "workflow_run_id": run.id,
                        "data": {"step_order": step.step_order, "step_type": step.step_type.value},
                    }
                elif marker == "step_event":
                    inner = item["event"]
                    yield {
                        "event_type": f"WorkflowStep:{inner['event_type']}",
                        "workflow_run_id": run.id,
                        "data": {"step_order": step.step_order, **inner["payload"]},
                    }
                elif marker == "workflow_step_completed":
                    if current_run_step is not None:
                        await self.run_service.complete_step(current_run_step, item["step_output"])
                        await self.session.commit()
                    yield {
                        "event_type": "WorkflowStepCompleted",
                        "workflow_run_id": run.id,
                        "data": {"step_order": step.step_order, "output": item["step_output"]},
                    }
                elif marker == "workflow_step_failed":
                    if current_run_step is not None:
                        await self.run_service.fail_step(current_run_step, item["error"])
                        await self.session.commit()
                    yield {
                        "event_type": "WorkflowStepFailed",
                        "workflow_run_id": run.id,
                        "data": {"step_order": step.step_order, "error": item["error"]},
                    }
        except RuntimeExecutionError as exc:
            await self.run_service.mark_failed(run, str(exc))
            await self.session.commit()
            yield {"event_type": "WorkflowFailed", "workflow_run_id": run.id, "data": {"error": str(exc)}}
            return

        final_result = context.stepResults.get(max(context.stepResults.keys()), "") if context.stepResults else ""
        await self.message_repo.create(
            session_id=chat_session.id, run_id=None, role=MessageRole.assistant, content=final_result
        )
        await self.run_service.mark_completed(run, final_result)
        await self.session.commit()

        yield {
            "event_type": "WorkflowCompleted",
            "workflow_run_id": run.id,
            "data": {"result": final_result},
        }
