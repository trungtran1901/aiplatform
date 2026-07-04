from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.models.hierarchy import Agent
from app.models.skill import AgentSkill, Skill, SkillCapability
from app.repositories.base import BaseRepository


class SkillRepository(BaseRepository[Skill]):
    model = Skill

    async def get_by_code(self, code: str, *, include_deleted: bool = False) -> Skill | None:
        stmt = select(Skill).where(Skill.code == code)
        if not include_deleted:
            stmt = stmt.where(Skill.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_capability_codes(self, skill_id: uuid.UUID) -> list[str]:
        stmt = select(SkillCapability.capability_code).where(SkillCapability.skill_id == skill_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_capability_codes(self, skill_id: uuid.UUID, codes: list[str]) -> None:
        await self.session.execute(delete(SkillCapability).where(SkillCapability.skill_id == skill_id))
        for code in set(codes):
            self.session.add(SkillCapability(skill_id=skill_id, capability_code=code))
        await self.session.flush()

    async def assign_to_agent(self, agent_id: uuid.UUID, skill_id: uuid.UUID) -> AgentSkill:
        link = AgentSkill(agent_id=agent_id, skill_id=skill_id)
        self.session.add(link)
        await self.session.flush()
        return link

    async def unassign_from_agent(self, agent_id: uuid.UUID, skill_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(AgentSkill).where(AgentSkill.agent_id == agent_id, AgentSkill.skill_id == skill_id)
        )
        await self.session.flush()

    async def get_capability_codes_for_agent(self, agent_id: uuid.UUID) -> list[str]:
        """All capability codes contributed by skills assigned to this agent."""
        stmt = (
            select(SkillCapability.capability_code)
            .join(AgentSkill, AgentSkill.skill_id == SkillCapability.skill_id)
            .where(AgentSkill.agent_id == agent_id)
        )
        result = await self.session.execute(stmt)
        return list(set(result.scalars().all()))

    async def list_agents_for_skill(
        self, skill_id: uuid.UUID, *, offset: int = 0, limit: int = 50, include_deleted_agents: bool = False
    ) -> tuple[list[Agent], int]:
        """Every Agent this Skill is currently assigned to - answers
        "who has this skill?" (the reverse of /agents/{id}/skills).
        Excludes soft-deleted agents by default, since a deleted agent
        having a stale agent_skills row isn't meaningful to a caller
        asking "which agents currently use this skill."
        """
        stmt = (
            select(Agent)
            .join(AgentSkill, AgentSkill.agent_id == Agent.id)
            .where(AgentSkill.skill_id == skill_id)
        )
        if not include_deleted_agents:
            stmt = stmt.where(Agent.deleted_at.is_(None))

        count_result = await self.session.execute(stmt.with_only_columns(Agent.id))
        total = len(count_result.scalars().all())

        stmt = stmt.order_by(Agent.created_at.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_skills_for_agent(self, agent_id: uuid.UUID) -> list[Skill]:
        """Every Skill currently assigned to this Agent - the reverse
        direction of list_agents_for_skill, exposed at
        GET /agents/{id}/skills for symmetry."""
        stmt = (
            select(Skill)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .where(AgentSkill.agent_id == agent_id, Skill.deleted_at.is_(None))
            .order_by(Skill.code.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
