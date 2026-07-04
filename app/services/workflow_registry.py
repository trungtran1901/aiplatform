"""
WorkflowRegistry.

Metadata CRUD for Workflow + WorkflowStep, per spec's "Implement Workflow
Registry. Workflows must be configurable through APIs. No hardcoded
workflows." Resolves each step's human-facing agentCode/teamCode (the
shape used in the spec's JSON example) into stable agent_id/team_id
values at write time, scoped to the Workflow's own agent_os_id - codes
are only unique within an AgentOS/Team, never globally, so the registry
must know which AgentOS a workflow belongs to before it can resolve a
step's code.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.models.workflow import Workflow, WorkflowStepType
from app.repositories.hierarchy_repository import AgentOSRepository, AgentRepository, TeamRepository
from app.repositories.workflow_repository import WorkflowRepository, WorkflowStepRepository
from app.schemas.workflow import WorkflowCreate, WorkflowStepDefinition, WorkflowUpdate


class WorkflowRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workflow_repo = WorkflowRepository(session)
        self.step_repo = WorkflowStepRepository(session)
        self.agent_os_repo = AgentOSRepository(session)
        self.team_repo = TeamRepository(session)
        self.agent_repo = AgentRepository(session)

    async def _resolve_step_definitions(
        self, agent_os_id: uuid.UUID, steps: list[WorkflowStepDefinition]
    ) -> list[dict]:
        """Resolves each step's agentCode/teamCode into agent_id/team_id,
        validating the referenced Agent/Team actually exists under this
        Workflow's AgentOS (an agentCode from a different AgentOS must
        never silently resolve - codes are only unique per-scope)."""
        resolved: list[dict] = []
        for step in steps:
            if step.type == WorkflowStepType.agent:
                # agentCode is scoped to a Team, but the spec's step
                # definition only carries agentCode (no teamCode for
                # AGENT steps) - we search every team under this
                # AgentOS for a matching, enabled agent code.
                agent = await self._find_agent_by_code_in_agent_os(agent_os_id, step.agentCode)
                if agent is None:
                    raise NotFoundError(
                        f"No enabled agent with code '{step.agentCode}' found under this workflow's AgentOS"
                    )
                resolved.append(
                    {"step_type": WorkflowStepType.agent, "agent_id": agent.id, "team_id": None, "step_config": step.config}
                )
            else:
                team = await self.team_repo.get_by_code(agent_os_id, step.teamCode)
                if team is None:
                    raise NotFoundError(
                        f"No team with code '{step.teamCode}' found under this workflow's AgentOS"
                    )
                resolved.append(
                    {"step_type": WorkflowStepType.team, "agent_id": None, "team_id": team.id, "step_config": step.config}
                )
        return resolved

    async def _find_agent_by_code_in_agent_os(self, agent_os_id: uuid.UUID, agent_code: str):
        teams, _ = await self.team_repo.list_by_agent_os(agent_os_id, limit=500)
        for team in teams:
            agent = await self.agent_repo.get_by_code(team.id, agent_code)
            if agent is not None:
                return agent
        return None

    async def create_workflow(self, payload: WorkflowCreate) -> Workflow:
        agent_os = await self.agent_os_repo.get(payload.agent_os_id)
        if agent_os is None:
            raise NotFoundError(f"AgentOS {payload.agent_os_id} not found")

        existing = await self.workflow_repo.get_by_code(payload.agent_os_id, payload.code)
        if existing is not None:
            raise ConflictError(f"Workflow with code '{payload.code}' already exists under this AgentOS")

        if payload.team_id is not None:
            team = await self.team_repo.get(payload.team_id)
            if team is None or team.agent_os_id != payload.agent_os_id:
                raise ValidationFailedError("workflows.team_id must reference a team under the same AgentOS")

        workflow = await self.workflow_repo.create(
            agent_os_id=payload.agent_os_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            team_id=payload.team_id,
            enabled=payload.enabled,
            workflow_metadata=payload.workflow_metadata,
            created_by=payload.created_by,
        )

        resolved_steps = await self._resolve_step_definitions(payload.agent_os_id, payload.steps)
        await self.step_repo.replace_steps(workflow.id, resolved_steps)

        return await self.workflow_repo.get_with_steps(workflow.id)

    async def update_workflow(self, workflow_id: uuid.UUID, payload: WorkflowUpdate) -> Workflow:
        workflow = await self.workflow_repo.get_or_404(workflow_id)

        update_data = payload.model_dump(exclude_unset=True, exclude={"steps"})
        if update_data:
            workflow = await self.workflow_repo.update(workflow, **update_data)

        if payload.steps is not None:
            resolved_steps = await self._resolve_step_definitions(workflow.agent_os_id, payload.steps)
            await self.step_repo.replace_steps(workflow.id, resolved_steps)
            # replace_steps issues raw INSERT/DELETE against workflow_steps;
            # the ORM identity map still holds workflow.steps as it was
            # loaded before this call (a stale, cached collection), so we
            # must explicitly expire it before the final get_with_steps()
            # re-fetch, or SQLAlchemy will return the old (pre-update)
            # collection instead of re-querying it.
            self.session.expire(workflow, ["steps"])

        return await self.workflow_repo.get_with_steps(workflow.id)

    async def get_workflow(self, workflow_id: uuid.UUID) -> Workflow:
        workflow = await self.workflow_repo.get_with_steps(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        return workflow

    async def list_workflows(self, *, agent_os_id: uuid.UUID | None = None, offset: int = 0, limit: int = 50):
        if agent_os_id is not None:
            return await self.workflow_repo.list_by_agent_os(agent_os_id, offset=offset, limit=limit)
        return await self.workflow_repo.list(offset=offset, limit=limit)

    async def delete_workflow(self, workflow_id: uuid.UUID) -> None:
        workflow = await self.workflow_repo.get_or_404(workflow_id)
        await self.workflow_repo.soft_delete(workflow)
