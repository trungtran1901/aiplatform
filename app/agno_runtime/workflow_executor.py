"""
WorkflowExecutor.

The orchestration loop itself: given an ordered list of WorkflowSteps and
an initial input, runs each step in sequence, threading each step's
output into the next step's input via WorkflowContext. Contains
absolutely no LLM/tool-calling logic of its own - every step is executed
by handing off to WorkflowRunner (which in turn hands off to
AgnoRuntimeEngine).

Execution flow (per spec):

    Input -> Step 1 -> Output -> Step 2 -> Output -> ... -> Step N

Deliberately NOT implemented here, per spec: branching, loops, parallel
execution, conditional logic, human approval steps. A WorkflowExecutor
instance always runs every step, in step_order, exactly once, and stops
at the first failure.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from app.agno_runtime.workflow_context import WorkflowContext
from app.agno_runtime.workflow_runner import WorkflowRunner
from app.core.exceptions import RuntimeExecutionError
from app.core.logging import get_logger
from app.models.workflow import WorkflowStep

logger = get_logger(__name__)


class StepExecutionResult:
    __slots__ = ("step", "output", "error")

    def __init__(self, step: WorkflowStep, output: str | None = None, error: str | None = None) -> None:
        self.step = step
        self.output = output
        self.error = error


class WorkflowExecutor:
    def __init__(self, runner: WorkflowRunner) -> None:
        self.runner = runner

    async def execute(
        self,
        steps: list[WorkflowStep],
        initial_input: str,
        context: WorkflowContext,
        *,
        on_step_started=None,
        on_step_completed=None,
        on_step_failed=None,
    ) -> str:
        """Runs every step in order, non-streaming. Returns the final
        step's output. Raises RuntimeExecutionError on the first step
        failure - no partial-success/skip-ahead semantics in Phase 1.

        The optional on_step_* callbacks (each `async def cb(step) -> Any`
        / `async def cb(step, output)` / `async def cb(step, error)`) let
        a caller (WorkflowExecutionService) persist per-step
        WorkflowRunStep records atomically as each step actually starts/
        finishes, without duplicating this loop's sequencing logic. They
        are awaited synchronously in-line - a failing callback aborts the
        run the same as a failing step would.
        """
        if not steps:
            raise RuntimeExecutionError("Workflow has no steps to execute")

        current_output = initial_input
        for step in sorted(steps, key=lambda s: s.step_order):
            step_input = context.previous_output(step.step_order, initial_input)
            logger.info(
                "workflow_step_executing",
                workflow_run_id=str(context.workflowRunId),
                step_order=step.step_order,
                step_type=step.step_type.value,
            )
            if on_step_started is not None:
                await on_step_started(step, step_input)
            try:
                current_output = await self.runner.run_step(step, step_input, context)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "workflow_step_failed",
                    workflow_run_id=str(context.workflowRunId),
                    step_order=step.step_order,
                    error=str(exc),
                )
                if on_step_failed is not None:
                    await on_step_failed(step, str(exc))
                raise RuntimeExecutionError(
                    f"Workflow step {step.step_order} ({step.step_type.value}) failed: {exc}"
                ) from exc

            if on_step_completed is not None:
                await on_step_completed(step, current_output)
            context.record_result(step.step_order, current_output)

        return current_output

    async def execute_stream(
        self,
        steps: list[WorkflowStep],
        initial_input: str,
        context: WorkflowContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming variant: yields a `workflow_step_started` marker
        before each step, forwards every event the underlying
        Agent/Team run produces (tagged with which step it belongs to),
        and a `workflow_step_completed` marker after each step
        succeeds. Stops and yields a single `workflow_step_failed` event
        on the first failure - no further steps run after that.
        """
        if not steps:
            raise RuntimeExecutionError("Workflow has no steps to execute")

        ordered_steps = sorted(steps, key=lambda s: s.step_order)
        for step in ordered_steps:
            step_input = context.previous_output(step.step_order, initial_input)

            yield {
                "marker": "workflow_step_started",
                "step": step,
                "step_input": step_input,
            }

            collected_output: list[str] = []
            try:
                async for event in self.runner.run_step_stream(step, step_input, context):
                    if event["payload"].get("is_assistant_content"):
                        collected_output.append(str(event["payload"].get("content", "")))
                    yield {"marker": "step_event", "step": step, "event": event}
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "workflow_step_failed",
                    workflow_run_id=str(context.workflowRunId),
                    step_order=step.step_order,
                    error=str(exc),
                )
                yield {"marker": "workflow_step_failed", "step": step, "error": str(exc)}
                raise RuntimeExecutionError(
                    f"Workflow step {step.step_order} ({step.step_type.value}) failed: {exc}"
                ) from exc

            step_output = "".join(collected_output)
            context.record_result(step.step_order, step_output)

            yield {
                "marker": "workflow_step_completed",
                "step": step,
                "step_output": step_output,
            }
