"""
Capability resolution service.

Allowed tools = intersection(agent_os_capabilities, team_capabilities, agent_capabilities)

This also folds in capabilities contributed by Skills assigned to the
Agent (an agent's *effective* agent-level capability set is the union of
its direct agent_capabilities assignments plus everything contributed by
its assigned skills) before intersecting with AgentOS and Team scope.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CapabilityResolutionError
from app.core.logging import get_logger
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.hierarchy_repository import AgentRepository, AgentOSRepository, TeamRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.capability import CapabilityResolutionResult

logger = get_logger(__name__)


class CapabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cap_repo = CapabilityRepository(session)
        self.skill_repo = SkillRepository(session)
        self.agent_os_repo = AgentOSRepository(session)
        self.team_repo = TeamRepository(session)
        self.agent_repo = AgentRepository(session)

    async def resolve(
        self,
        agent_os_id: uuid.UUID,
        team_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> CapabilityResolutionResult:
        agent_os = await self.agent_os_repo.get(agent_os_id)
        team = await self.team_repo.get(team_id)
        agent = await self.agent_repo.get(agent_id)

        if agent_os is None or not agent_os.enabled:
            raise CapabilityResolutionError(f"AgentOS {agent_os_id} not found or disabled")
        if team is None or not team.enabled:
            raise CapabilityResolutionError(f"Team {team_id} not found or disabled")
        if agent is None or not agent.enabled:
            raise CapabilityResolutionError(f"Agent {agent_id} not found or disabled")

        agent_os_caps = set(await self.cap_repo.get_agent_os_capabilities(agent_os_id))
        team_caps = set(await self.cap_repo.get_team_capabilities(team_id))

        direct_agent_caps = set(await self.cap_repo.get_agent_capabilities(agent_id))
        skill_caps = set(await self.skill_repo.get_capability_codes_for_agent(agent_id))
        effective_agent_caps = direct_agent_caps | skill_caps

        effective = agent_os_caps & team_caps & effective_agent_caps

        logger.info(
            "capability_resolution",
            agent_os_id=str(agent_os_id),
            team_id=str(team_id),
            agent_id=str(agent_id),
            agent_os_count=len(agent_os_caps),
            team_count=len(team_caps),
            agent_count=len(effective_agent_caps),
            effective_count=len(effective),
        )

        return CapabilityResolutionResult(
            agent_os_capabilities=sorted(agent_os_caps),
            team_capabilities=sorted(team_caps),
            agent_capabilities=sorted(effective_agent_caps),
            effective_capabilities=sorted(effective),
        )
