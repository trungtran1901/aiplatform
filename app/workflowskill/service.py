"""
WorkflowSkillService.

build_trigger_tools(agent_id, ...) returns one callable per WORKFLOW
Skill assigned to the Agent - an empty list if none, exactly like
KnowledgeSkillService.build_source_lookup_tool returning None for an
Agent with no Knowledge skills, so callers can always safely extend
`tools` with whatever this returns without checking anything themselves.

SCOPING: a Workflow is only resolvable within the SAME AgentOS the
calling Agent belongs to (Workflow.code is only unique per-AgentOS, same
constraint WorkflowRegistry already enforces on creation) - a Skill
whose config.workflowCode doesn't resolve to an enabled Workflow under
that AgentOS is silently skipped (logged as a warning), never raised,
so one misconfigured Skill can never break an Agent's other tools.

SAFETY: see app.core.workflow_trigger_context for the depth/cycle guard
applied around every actual trigger.
"""
from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RuntimeExecutionError
from app.core.logging import get_logger
from app.core.workflow_trigger_context import enter_workflow_trigger
from app.models.skill import SkillType
from app.repositories.skill_repository import SkillRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.workflowskill.models import WorkflowSkillConfig

logger = get_logger(__name__)


class WorkflowSkillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skill_repo = SkillRepository(session)
        self.workflow_repo = WorkflowRepository(session)

    async def build_trigger_tools(
        self,
        agent_id: uuid.UUID,
        *,
        agent_os_id: uuid.UUID,
        session_id: str,
        user_id: str | None,
    ) -> list[Callable]:
        skills = await self.skill_repo.list_skills_for_agent(agent_id)
        workflow_skills = [s for s in skills if s.skill_type == SkillType.workflow]
        if not workflow_skills:
            return []

        tools: list[Callable] = []
        for skill in workflow_skills:
            try:
                config = WorkflowSkillConfig.model_validate(skill.config or {})
            except Exception as exc:  # noqa: BLE001
                logger.warning("workflow_skill_config_invalid", skill_code=skill.code, error=str(exc))
                continue

            workflow = await self.workflow_repo.get_by_code(agent_os_id, config.workflowCode)
            if workflow is None or not workflow.enabled:
                logger.warning(
                    "workflow_skill_target_not_found",
                    skill_code=skill.code,
                    workflow_code=config.workflowCode,
                    agent_os_id=str(agent_os_id),
                )
                continue

            tools.append(
                self._make_trigger_tool(
                    workflow_id=workflow.id,
                    workflow_code=workflow.code,
                    workflow_name=workflow.name,
                    workflow_description=workflow.description,
                    max_depth=config.maxTriggerDepth,
                    session_id=session_id,
                    user_id=user_id,
                )
            )

        return tools

    def _make_trigger_tool(
        self,
        *,
        workflow_id: uuid.UUID,
        workflow_code: str,
        workflow_name: str,
        workflow_description: str | None,
        max_depth: int,
        session_id: str,
        user_id: str | None,
    ) -> Callable:
        # Deferred imports: WorkflowExecutionService constructs its own
        # fresh AgnoRuntimeEngine internally, and AgnoRuntimeEngine is
        # what builds THIS service's tools in the first place - importing
        # at call time rather than module load time avoids a circular
        # import between the two modules.
        from app.schemas.workflow_run import WorkflowRunRequest
        from app.services.workflow_execution_service import WorkflowExecutionService

        description = workflow_description or f"Executes the '{workflow_name}' workflow."

        async def trigger_workflow(input: str) -> str:  # noqa: A002 - matches Agno tool-arg convention
            try:
                with enter_workflow_trigger(workflow_code, max_depth=max_depth):
                    service = WorkflowExecutionService(self.session)
                    request = WorkflowRunRequest(
                        input=input,
                        session_id=uuid.UUID(session_id) if session_id else None,
                        user_id=user_id,
                    )
                    result = await service.run_workflow(workflow_id, request)
                logger.info(
                    "workflow_triggered_by_agent", workflow_code=workflow_code, status=result["status"]
                )
                return result["result"] or "(workflow completed with empty result)"
            except RuntimeExecutionError as exc:
                logger.warning("workflow_trigger_blocked", workflow_code=workflow_code, error=str(exc))
                return f"Không thể chạy workflow '{workflow_code}': {exc}"

        # Agno derives each tool's exposed name from the function's
        # __name__ - set dynamically so an Agent with multiple WORKFLOW
        # skills gets one distinctly-named tool per workflow, e.g.
        # "trigger_workflow_leave_request_flow", not N identical
        # closures all named "trigger_workflow".
        trigger_workflow.__name__ = f"trigger_workflow_{workflow_code}"
        trigger_workflow.__doc__ = (
            f"Trigger the '{workflow_name}' workflow ({workflow_code}). {description} "
            f"Call this with `input` describing the task/data for the workflow's first step. "
            f"Only call this when the user's request genuinely requires this specific "
            f"multi-step workflow rather than something you can answer or do directly."
        )
        return trigger_workflow