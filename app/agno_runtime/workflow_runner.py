"""
WorkflowRunner.

Executes exactly one WorkflowStep, delegating all actual LLM/tool
execution to the existing AgnoRuntimeEngine (engine.run / engine.run_team)
- this module contains no agent-execution logic of its own, per the
spec's explicit "Reuse existing Agent execution / Team execution, do not
duplicate logic" requirement.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from app.agno_runtime.engine import AgnoRuntimeEngine
from app.agno_runtime.workflow_context import WorkflowContext
from app.core.exceptions import RuntimeExecutionError
from app.core.logging import get_logger
from app.models.workflow import WorkflowStep, WorkflowStepType

logger = get_logger(__name__)


class WorkflowRunner:
    def __init__(self, engine: AgnoRuntimeEngine) -> None:
        self.engine = engine

    async def run_step(
        self,
        step: WorkflowStep,
        step_input: str,
        context: WorkflowContext,
    ) -> str:
        """Non-streaming execution of one step. Returns the step's text
        output, which becomes the next step's input."""
        if step.step_type == WorkflowStepType.agent:
            if step.agent_id is None:
                raise RuntimeExecutionError(f"WorkflowStep {step.id} is type=AGENT but has no agent_id")
            context.agentId = step.agent_id
            context.teamId = None
            ctx = await self.engine.resolve_context_by_id(step.agent_id)
            return await self.engine.run(
                ctx,
                step_input,
                session_id=str(context.sessionId),
                user_id=context.userId,
            )

        if step.step_type == WorkflowStepType.team:
            if step.team_id is None:
                raise RuntimeExecutionError(f"WorkflowStep {step.id} is type=TEAM but has no team_id")
            context.teamId = step.team_id
            context.agentId = None
            team_ctx = await self.engine.resolve_team_context_by_id(step.team_id)
            return await self.engine.run_team(
                team_ctx,
                step_input,
                session_id=str(context.sessionId),
                user_id=context.userId,
            )

        raise RuntimeExecutionError(f"Unsupported WorkflowStep.step_type: {step.step_type}")

    async def run_step_stream(
        self,
        step: WorkflowStep,
        step_input: str,
        context: WorkflowContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming execution of one step, yielding the same normalized
        event dicts AgnoRuntimeEngine.run_stream/run_team_stream produce
        - WorkflowExecutor wraps these into WorkflowStepStarted/Completed
        events without needing to know which underlying execution path
        produced them."""
        if step.step_type == WorkflowStepType.agent:
            if step.agent_id is None:
                raise RuntimeExecutionError(f"WorkflowStep {step.id} is type=AGENT but has no agent_id")
            context.agentId = step.agent_id
            context.teamId = None
            ctx = await self.engine.resolve_context_by_id(step.agent_id)
            async for event in self.engine.run_stream(
                ctx,
                step_input,
                session_id=str(context.sessionId),
                user_id=context.userId,
            ):
                yield event
            return

        if step.step_type == WorkflowStepType.team:
            if step.team_id is None:
                raise RuntimeExecutionError(f"WorkflowStep {step.id} is type=TEAM but has no team_id")
            context.teamId = step.team_id
            context.agentId = None
            team_ctx = await self.engine.resolve_team_context_by_id(step.team_id)
            async for event in self.engine.run_team_stream(
                team_ctx,
                step_input,
                session_id=str(context.sessionId),
                user_id=context.userId,
            ):
                yield event
            return

        raise RuntimeExecutionError(f"Unsupported WorkflowStep.step_type: {step.step_type}")
