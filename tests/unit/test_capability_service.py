"""Tests for CapabilityService.resolve - the intersection logic that
determines the effective tool set for an agent run.

This is the single most important invariant in the platform: allowed
tools = intersection(agent_os_capabilities, team_capabilities,
agent_capabilities (+ skill-contributed capabilities)). These tests pin
that behavior down explicitly.
"""
from __future__ import annotations

import pytest

from app.core.exceptions import CapabilityResolutionError
from app.models.hierarchy import Agent, AgentOS, Team
from app.models.skill import AgentSkill, Skill, SkillCapability
from app.repositories.capability_repository import CapabilityRepository
from app.services.capability_service import CapabilityService

pytestmark = pytest.mark.asyncio


async def _build_hierarchy(db_session):
    agent_os = AgentOS(code="enterprise", name="Enterprise", enabled=True)
    db_session.add(agent_os)
    await db_session.flush()

    team = Team(agent_os_id=agent_os.id, code="sales", name="Sales", enabled=True)
    db_session.add(team)
    await db_session.flush()

    agent = Agent(team_id=team.id, code="lead-qualifier", name="Lead Qualifier", enabled=True)
    db_session.add(agent)
    await db_session.flush()

    return agent_os, team, agent


async def test_intersection_only_keeps_codes_present_at_all_three_levels(db_session):
    agent_os, team, agent = await _build_hierarchy(db_session)
    cap_repo = CapabilityRepository(db_session)

    await cap_repo.set_agent_os_capabilities(agent_os.id, ["crm.customer.create", "crm.customer.search", "erp.invoice.create"])
    await cap_repo.set_team_capabilities(team.id, ["crm.customer.create", "crm.customer.search"])
    await cap_repo.set_agent_capabilities(agent.id, ["crm.customer.create"])
    await db_session.flush()

    service = CapabilityService(db_session)
    result = await service.resolve(agent_os.id, team.id, agent.id)

    assert result.effective_capabilities == ["crm.customer.create"]
    assert "erp.invoice.create" not in result.effective_capabilities
    assert "crm.customer.search" not in result.effective_capabilities


async def test_empty_intersection_when_no_overlap(db_session):
    agent_os, team, agent = await _build_hierarchy(db_session)
    cap_repo = CapabilityRepository(db_session)

    await cap_repo.set_agent_os_capabilities(agent_os.id, ["crm.customer.create"])
    await cap_repo.set_team_capabilities(team.id, ["erp.invoice.create"])
    await cap_repo.set_agent_capabilities(agent.id, ["hr.employee.lookup"])
    await db_session.flush()

    service = CapabilityService(db_session)
    result = await service.resolve(agent_os.id, team.id, agent.id)

    assert result.effective_capabilities == []


async def test_skill_contributed_capabilities_are_folded_into_agent_level(db_session):
    agent_os, team, agent = await _build_hierarchy(db_session)
    cap_repo = CapabilityRepository(db_session)

    skill = Skill(code="customer-management", name="Customer Management")
    db_session.add(skill)
    await db_session.flush()
    db_session.add(SkillCapability(skill_id=skill.id, capability_code="crm.customer.create"))
    db_session.add(AgentSkill(agent_id=agent.id, skill_id=skill.id))
    await db_session.flush()

    # Note: NO direct agent_capabilities assignment - capability comes
    # entirely from the assigned skill.
    await cap_repo.set_agent_os_capabilities(agent_os.id, ["crm.customer.create"])
    await cap_repo.set_team_capabilities(team.id, ["crm.customer.create"])
    await db_session.flush()

    service = CapabilityService(db_session)
    result = await service.resolve(agent_os.id, team.id, agent.id)

    assert result.effective_capabilities == ["crm.customer.create"]


async def test_disabled_agent_os_raises_capability_resolution_error(db_session):
    agent_os, team, agent = await _build_hierarchy(db_session)
    agent_os.enabled = False
    await db_session.flush()

    service = CapabilityService(db_session)
    with pytest.raises(CapabilityResolutionError):
        await service.resolve(agent_os.id, team.id, agent.id)


async def test_disabled_team_raises_capability_resolution_error(db_session):
    agent_os, team, agent = await _build_hierarchy(db_session)
    team.enabled = False
    await db_session.flush()

    service = CapabilityService(db_session)
    with pytest.raises(CapabilityResolutionError):
        await service.resolve(agent_os.id, team.id, agent.id)


async def test_disabled_agent_raises_capability_resolution_error(db_session):
    agent_os, team, agent = await _build_hierarchy(db_session)
    agent.enabled = False
    await db_session.flush()

    service = CapabilityService(db_session)
    with pytest.raises(CapabilityResolutionError):
        await service.resolve(agent_os.id, team.id, agent.id)
