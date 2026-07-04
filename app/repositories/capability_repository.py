from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.models.capability import AgentCapability, AgentOSCapability, TeamCapability


class CapabilityRepository:
    """Manages the 3 capability-assignment tables. Not a BaseRepository
    subclass since these are pure association tables without soft delete."""

    def __init__(self, session) -> None:
        self.session = session

    # --- AgentOS level ---
    async def get_agent_os_capabilities(self, agent_os_id: uuid.UUID) -> list[str]:
        stmt = select(AgentOSCapability.capability_code).where(
            AgentOSCapability.agent_os_id == agent_os_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_agent_os_capabilities(self, agent_os_id: uuid.UUID, codes: list[str]) -> None:
        await self.session.execute(
            delete(AgentOSCapability).where(AgentOSCapability.agent_os_id == agent_os_id)
        )
        for code in set(codes):
            self.session.add(AgentOSCapability(agent_os_id=agent_os_id, capability_code=code))
        await self.session.flush()

    # --- Team level ---
    async def get_team_capabilities(self, team_id: uuid.UUID) -> list[str]:
        stmt = select(TeamCapability.capability_code).where(TeamCapability.team_id == team_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_team_capabilities(self, team_id: uuid.UUID, codes: list[str]) -> None:
        await self.session.execute(delete(TeamCapability).where(TeamCapability.team_id == team_id))
        for code in set(codes):
            self.session.add(TeamCapability(team_id=team_id, capability_code=code))
        await self.session.flush()

    # --- Agent level ---
    async def get_agent_capabilities(self, agent_id: uuid.UUID) -> list[str]:
        stmt = select(AgentCapability.capability_code).where(AgentCapability.agent_id == agent_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_agent_capabilities(self, agent_id: uuid.UUID, codes: list[str]) -> None:
        await self.session.execute(delete(AgentCapability).where(AgentCapability.agent_id == agent_id))
        for code in set(codes):
            self.session.add(AgentCapability(agent_id=agent_id, capability_code=code))
        await self.session.flush()
