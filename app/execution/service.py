"""
ExecutionEngineService.

Executes one ExecutionPlan, persisting an ExecutionPlanRun +
ExecutionPlanStepRun timeline (mirrors WorkflowRunService's pattern -
app/services/workflow_run_service.py). Each step is retried up to
`PlanStep.max_retries` times via tenacity before the whole plan run is
marked failed - stops at the first step that exhausts its retries (no
skip-ahead / partial-success semantics, same philosophy as
WorkflowExecutor).

Disabled by default: run_plan() raises RuntimeExecutionError immediately
if FEATURE_EXECUTION_ENGINE is off, so nothing calls this accidentally
in a deployment that hasn't opted in.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, stop_after_attempt, wait_fixed, retry_if_exception_type

from app.agno_runtime.engine import AgnoRuntimeEngine
from app.core.config import get_settings
from app.core.exceptions import RuntimeExecutionError
from app.core.logging import get_logger
from app.models.execution_plan_run import ExecutionPlanRunStatus, ExecutionStepStatus
from app.planning.models import ExecutionPlan, PlanStepTargetType
from app.repositories.execution_plan_repository import ExecutionPlanRunRepository, ExecutionPlanStepRunRepository

logger = get_logger(__name__)


class ExecutionEngineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.engine = AgnoRuntimeEngine(session)
        self.plan_run_repo = ExecutionPlanRunRepository(session)
        self.step_run_repo = ExecutionPlanStepRunRepository(session)

    async def run_plan(
        self,
        plan: ExecutionPlan,
        *,
        session_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not get_settings().FEATURE_EXECUTION_ENGINE:
            raise RuntimeExecutionError("Execution Engine is not enabled on this deployment")
        if not plan.steps:
            raise RuntimeExecutionError("ExecutionPlan has no steps to execute")

        plan_run = await self.plan_run_repo.create(
            session_id=session_id, input=plan.original_message, rationale=plan.rationale,
            status=ExecutionPlanRunStatus.running, started_at=datetime.now(timezone.utc),
        )

        current_output = plan.original_message
        for step in sorted(plan.steps, key=lambda s: s.order):
            step_input = step.step_input_template or current_output
            target_code = step.team_code if step.target_type == PlanStepTargetType.team else step.agent_code

            step_run = await self.step_run_repo.create(
                plan_run_id=plan_run.id, step_order=step.order,
                target_type=step.target_type.value, target_code=target_code or "",
                status=ExecutionStepStatus.running, input=step_input,
                started_at=datetime.now(timezone.utc),
            )

            try:
                current_output = await self._execute_step_with_retry(
                    step, step_input, step_run, session_id=session_id, user_id=user_id
                )
            except Exception as exc:  # noqa: BLE001
                step_run.status = ExecutionStepStatus.failed
                step_run.error_message = str(exc)
                step_run.completed_at = datetime.now(timezone.utc)
                await self.session.flush()

                plan_run.status = ExecutionPlanRunStatus.failed
                plan_run.error_message = str(exc)
                plan_run.completed_at = datetime.now(timezone.utc)
                await self.session.flush()

                logger.error("execution_plan_step_failed", step_order=step.order, error=str(exc))
                raise RuntimeExecutionError(f"Execution plan step {step.order} failed: {exc}") from exc

            step_run.status = ExecutionStepStatus.completed
            step_run.output = current_output
            step_run.completed_at = datetime.now(timezone.utc)
            await self.session.flush()

        plan_run.status = ExecutionPlanRunStatus.completed
        plan_run.result = current_output
        plan_run.completed_at = datetime.now(timezone.utc)
        await self.session.flush()

        return {"planRunId": plan_run.id, "status": plan_run.status.value, "result": current_output}

    async def _execute_step_with_retry(
        self, step, step_input: str, step_run, *, session_id: str, user_id: str | None
    ) -> str:
        attempts = max(1, step.max_retries + 1)

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_fixed(1),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                step_run.attempt_count += 1
                if step_run.attempt_count > 1:
                    step_run.status = ExecutionStepStatus.retrying
                    await self.session.flush()

                if step.target_type == PlanStepTargetType.team:
                    ctx = await self.engine.resolve_team_context_by_code(step.agent_os_code, step.team_code)
                    return await self.engine.run_team(ctx, step_input, session_id=session_id, user_id=user_id)

                ctx = await self.engine.resolve_context(step.agent_os_code, step.team_code or "", step.agent_code)
                return await self.engine.run(ctx, step_input, session_id=session_id, user_id=user_id)

        raise RuntimeExecutionError("Execution step retry loop exited without a result")  # pragma: no cover
