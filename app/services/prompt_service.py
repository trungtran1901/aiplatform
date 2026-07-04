"""
Prompt composition service.

Final Runtime Prompt = AgentOS Prompt + Team Prompt + Agent Prompt

Composition is additive/sectioned (not override): each level contributes
its own section to the final system prompt, going from most general
(AgentOS) to most specific (Agent). This lets the AgentOS define
organization-wide tone/constraints, the Team define domain-specific
context, and the Agent define its precise task instructions, without any
level needing to know about or repeat the others' content.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.hierarchy import Agent, AgentOS, Team
from app.models.prompt import Prompt
from app.repositories.prompt_repository import PromptRepository

logger = get_logger(__name__)


class PromptCompositionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.prompt_repo = PromptRepository(session)

    async def _resolve_prompt_content(self, prompt_id: uuid.UUID | None) -> str | None:
        if prompt_id is None:
            return None
        prompt: Prompt | None = await self.prompt_repo.get(prompt_id)
        if prompt is None:
            return None
        return prompt.content

    async def compose(self, agent_os: AgentOS, team: Team, agent: Agent) -> str:
        sections: list[str] = []

        agent_os_prompt = await self._resolve_prompt_content(agent_os.shared_prompt_id)
        if agent_os_prompt:
            sections.append(f"# Organization Context ({agent_os.code})\n{agent_os_prompt}")

        team_prompt = await self._resolve_prompt_content(team.team_prompt_id)
        if team_prompt:
            sections.append(f"# Team Context ({team.code})\n{team_prompt}")

        agent_prompt = await self._resolve_prompt_content(agent.prompt_id)
        if agent_prompt:
            sections.append(f"# Agent Instructions ({agent.code})\n{agent_prompt}")

        final_prompt = "\n\n".join(sections) if sections else (
            f"You are {agent.name}, an agent within team {team.name}."
        )

        logger.info(
            "prompt_composed",
            agent_os_code=agent_os.code,
            team_code=team.code,
            agent_code=agent.code,
            section_count=len(sections),
        )
        return final_prompt

    async def compose_team_only(self, agent_os: AgentOS, team: Team) -> str:
        """Composes AgentOS + Team sections only (no Agent section),
        used as the coordinating Team's own instructions when executing
        a full Team run (agno.team.Team) rather than a single Agent.
        Member agents within the Team still get their own full
        AgentOS+Team+Agent prompt via compose() - this is purely the
        Team coordinator's instructions.
        """
        sections: list[str] = []

        agent_os_prompt = await self._resolve_prompt_content(agent_os.shared_prompt_id)
        if agent_os_prompt:
            sections.append(f"# Organization Context ({agent_os.code})\n{agent_os_prompt}")

        team_prompt = await self._resolve_prompt_content(team.team_prompt_id)
        if team_prompt:
            sections.append(f"# Team Context ({team.code})\n{team_prompt}")

        final_prompt = "\n\n".join(sections) if sections else (
            f"You are the coordinator for team {team.name}. "
            f"Delegate to your team members as appropriate and synthesize their responses."
        )

        logger.info(
            "team_prompt_composed",
            agent_os_code=agent_os.code,
            team_code=team.code,
            section_count=len(sections),
        )
        return final_prompt

    async def compose_root_only(self, agent_os: AgentOS) -> str:
        """Composes the AgentOS-level routing instructions for a root
        team that dispatches to child teams. This is used when a caller
        specifies only an AgentOS and wants Agno to decide which Team
        should handle the request.
        """
        sections: list[str] = []

        agent_os_prompt = await self._resolve_prompt_content(agent_os.shared_prompt_id)
        if agent_os_prompt:
            sections.append(f"# Organization Context ({agent_os.code})\n{agent_os_prompt}")

        final_prompt = "\n\n".join(sections) if sections else (
            "You are the router for this AgentOS. "
            "Inspect the incoming request and delegate it to the most appropriate team."
        )

        logger.info(
            "root_prompt_composed",
            agent_os_code=agent_os.code,
            section_count=len(sections),
        )
        return final_prompt
