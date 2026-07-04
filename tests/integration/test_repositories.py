"""Integration tests for the repository layer against a real (SQLite)
database session, validating soft-delete semantics, unique code lookups,
and pagination."""
from __future__ import annotations

import pytest

from app.repositories.hierarchy_repository import AgentOSRepository, AgentRepository, TeamRepository

pytestmark = pytest.mark.asyncio


async def test_create_and_get_agent_os(db_session):
    repo = AgentOSRepository(db_session)
    obj = await repo.create(code="enterprise", name="Enterprise", enabled=True)

    fetched = await repo.get(obj.id)
    assert fetched is not None
    assert fetched.code == "enterprise"


async def test_get_by_code_returns_none_when_not_found(db_session):
    repo = AgentOSRepository(db_session)
    result = await repo.get_by_code("does-not-exist")
    assert result is None


async def test_soft_delete_excludes_from_get_and_list(db_session):
    repo = AgentOSRepository(db_session)
    obj = await repo.create(code="enterprise", name="Enterprise", enabled=True)

    await repo.soft_delete(obj)

    assert await repo.get(obj.id) is None
    assert await repo.get(obj.id, include_deleted=True) is not None

    items, total = await repo.list()
    assert obj.id not in [i.id for i in items]
    assert total == 0


async def test_pagination_offset_and_limit(db_session):
    repo = AgentOSRepository(db_session)
    for i in range(5):
        await repo.create(code=f"os-{i}", name=f"OS {i}", enabled=True)

    page1, total = await repo.list(offset=0, limit=2)
    page2, _ = await repo.list(offset=2, limit=2)

    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {o.id for o in page1}.isdisjoint({o.id for o in page2})


async def test_team_get_by_code_scoped_to_agent_os(db_session):
    agent_os_repo = AgentOSRepository(db_session)
    team_repo = TeamRepository(db_session)

    os1 = await agent_os_repo.create(code="enterprise", name="Enterprise", enabled=True)
    os2 = await agent_os_repo.create(code="retail", name="Retail", enabled=True)

    await team_repo.create(agent_os_id=os1.id, code="sales", name="Sales", enabled=True)
    await team_repo.create(agent_os_id=os2.id, code="sales", name="Sales (Retail)", enabled=True)

    found_in_os1 = await team_repo.get_by_code(os1.id, "sales")
    found_in_os2 = await team_repo.get_by_code(os2.id, "sales")

    assert found_in_os1.id != found_in_os2.id
    assert found_in_os1.name == "Sales"
    assert found_in_os2.name == "Sales (Retail)"


async def test_agent_get_first_enabled_in_team_skips_disabled(db_session):
    agent_os_repo = AgentOSRepository(db_session)
    team_repo = TeamRepository(db_session)
    agent_repo = AgentRepository(db_session)

    agent_os = await agent_os_repo.create(code="enterprise", name="Enterprise", enabled=True)
    team = await team_repo.create(agent_os_id=agent_os.id, code="sales", name="Sales", enabled=True)

    disabled_agent = await agent_repo.create(team_id=team.id, code="disabled-bot", name="Disabled", enabled=False)
    enabled_agent = await agent_repo.create(team_id=team.id, code="active-bot", name="Active", enabled=True)

    found = await agent_repo.get_first_enabled_in_team(team.id)
    assert found.id == enabled_agent.id
    assert found.id != disabled_agent.id
