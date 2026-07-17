"""
PlanningEngineService.

Produces an ExecutionPlan for a chat turn. See app/planning/__init__.py
for the deliberate scope boundary (heuristic/deterministic today, LLM
planning is a documented extension point, not implemented).

Disabled by default: build_plan() always returns a single-step plan
identical to today's direct dispatch (agentOs/team/agent from the
request) when FEATURE_PLANNING_ENGINE is off, so callers can adopt this
unconditionally without changing behavior until the flag is turned on.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.planning.models import ExecutionPlan, PlanStep, PlanStepTargetType

logger = get_logger(__name__)


class PlanningEngineService:
    def build_plan(
        self,
        message: str,
        *,
        agent_os_code: str,
        team_code: str | None,
        agent_code: str | None,
        explicit_steps: list[dict] | None = None,
    ) -> ExecutionPlan:
        """`explicit_steps`, if given, is a caller-supplied ordered list
        of {"team_code"|"agent_code": "...", "input_template": "..."}
        dicts - the only "planning" this engine does today: honoring an
        explicit plan rather than inferring one. Extension point for
        real planning: replace this branch with an LLM call that
        returns the same explicit_steps shape.
        """
        settings = get_settings()

        if not settings.FEATURE_PLANNING_ENGINE or not explicit_steps:
            # Default / disabled: a single step identical to today's
            # direct dispatch - zero behavior change.
            step = PlanStep(
                target_type=PlanStepTargetType.team if team_code else PlanStepTargetType.agent,
                agent_os_code=agent_os_code,
                team_code=team_code,
                agent_code=agent_code,
                order=0,
            )
            return ExecutionPlan(original_message=message, steps=[step], rationale="single-step (default dispatch)")

        steps: list[PlanStep] = []
        for i, raw in enumerate(explicit_steps):
            target_team = raw.get("team_code")
            target_agent = raw.get("agent_code")
            steps.append(
                PlanStep(
                    target_type=PlanStepTargetType.team if target_team else PlanStepTargetType.agent,
                    agent_os_code=agent_os_code,
                    team_code=target_team,
                    agent_code=target_agent,
                    step_input_template=raw.get("input_template"),
                    max_retries=int(raw.get("max_retries", 0)),
                    order=i,
                )
            )
        logger.info("execution_plan_built", step_count=len(steps))
        return ExecutionPlan(original_message=message, steps=steps, rationale="explicit multi-step plan")
