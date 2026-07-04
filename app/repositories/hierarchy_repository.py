from __future__ import annotations

from sqlalchemy import select

from app.models.hierarchy import Agent, AgentOS, Team
from app.repositories.base import BaseRepository


class AgentOSRepository(BaseRepository[AgentOS]):
    model = AgentOS

    async def get_by_code(self, code: str, *, include_deleted: bool = False) -> AgentOS | None:
        stmt = select(AgentOS).where(AgentOS.code == code)
        if not include_deleted:
            stmt = stmt.where(AgentOS.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class TeamRepository(BaseRepository[Team]):
    model = Team

    async def get_by_code(
        self, agent_os_id, code: str, *, include_deleted: bool = False
    ) -> Team | None:
        stmt = select(Team).where(Team.agent_os_id == agent_os_id, Team.code == code)
        if not include_deleted:
            stmt = stmt.where(Team.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_agent_os(self, agent_os_id, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, agent_os_id=agent_os_id)


class AgentRepository(BaseRepository[Agent]):
    model = Agent

    async def get_by_code(self, team_id, code: str, *, include_deleted: bool = False) -> Agent | None:
        stmt = select(Agent).where(Agent.team_id == team_id, Agent.code == code)
        if not include_deleted:
            stmt = stmt.where(Agent.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_first_enabled_in_team(self, team_id) -> Agent | None:
        stmt = (
            select(Agent)
            .where(Agent.team_id == team_id, Agent.enabled.is_(True), Agent.deleted_at.is_(None))
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_team(self, team_id, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, team_id=team_id)
