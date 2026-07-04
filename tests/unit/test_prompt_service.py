"""Tests for PromptCompositionService.compose - verifies the additive
AgentOS + Team + Agent prompt composition behavior."""
from __future__ import annotations

import pytest

from app.models.hierarchy import Agent, AgentOS, Team
from app.models.prompt import Prompt, PromptStatus
from app.services.prompt_service import PromptCompositionService

pytestmark = pytest.mark.asyncio


async def test_compose_includes_all_three_levels_in_order(db_session):
    org_prompt = Prompt(code="org-base", name="Org Base", content="Be professional and concise.", version=1, status=PromptStatus.active)
    team_prompt = Prompt(code="sales-team", name="Sales Team", content="Focus on closing deals quickly.", version=1, status=PromptStatus.active)
    agent_prompt = Prompt(code="lead-qualifier", name="Lead Qualifier", content="Qualify leads using BANT criteria.", version=1, status=PromptStatus.active)
    db_session.add_all([org_prompt, team_prompt, agent_prompt])
    await db_session.flush()

    agent_os = AgentOS(code="enterprise", name="Enterprise", shared_prompt_id=org_prompt.id, enabled=True)
    db_session.add(agent_os)
    await db_session.flush()

    team = Team(agent_os_id=agent_os.id, code="sales", name="Sales", team_prompt_id=team_prompt.id, enabled=True)
    db_session.add(team)
    await db_session.flush()

    agent = Agent(team_id=team.id, code="lead-qualifier", name="Lead Qualifier", prompt_id=agent_prompt.id, enabled=True)
    db_session.add(agent)
    await db_session.flush()

    service = PromptCompositionService(db_session)
    final_prompt = await service.compose(agent_os, team, agent)

    assert "Be professional and concise." in final_prompt
    assert "Focus on closing deals quickly." in final_prompt
    assert "Qualify leads using BANT criteria." in final_prompt
    # Order: AgentOS section appears before Team section appears before Agent section
    assert final_prompt.index("Be professional") < final_prompt.index("Focus on closing")
    assert final_prompt.index("Focus on closing") < final_prompt.index("Qualify leads")


async def test_compose_falls_back_gracefully_when_no_prompts_assigned(db_session):
    agent_os = AgentOS(code="enterprise", name="Enterprise", enabled=True)
    db_session.add(agent_os)
    await db_session.flush()
    team = Team(agent_os_id=agent_os.id, code="sales", name="Sales", enabled=True)
    db_session.add(team)
    await db_session.flush()
    agent = Agent(team_id=team.id, code="bot", name="Bot", enabled=True)
    db_session.add(agent)
    await db_session.flush()

    service = PromptCompositionService(db_session)
    final_prompt = await service.compose(agent_os, team, agent)

    assert "Bot" in final_prompt
    assert "Sales" in final_prompt


async def test_compose_skips_missing_prompt_id_gracefully(db_session):
    """If a prompt_id points to a non-existent row, composition should
    not raise - it just omits that section."""
    import uuid

    agent_os = AgentOS(code="enterprise", name="Enterprise", shared_prompt_id=uuid.uuid4(), enabled=True)
    db_session.add(agent_os)
    await db_session.flush()
    team = Team(agent_os_id=agent_os.id, code="sales", name="Sales", enabled=True)
    db_session.add(team)
    await db_session.flush()
    agent = Agent(team_id=team.id, code="bot", name="Bot", enabled=True)
    db_session.add(agent)
    await db_session.flush()

    service = PromptCompositionService(db_session)
    final_prompt = await service.compose(agent_os, team, agent)
    assert final_prompt  # does not raise, returns a fallback
