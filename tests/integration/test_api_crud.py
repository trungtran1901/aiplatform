"""End-to-end API tests exercising the FastAPI app over an in-memory
SQLite database (DB dependency overridden), validating the full
request -> repository -> response cycle for the core metadata CRUD
surfaces."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models as m
from app.api.deps import get_db
from app.main import app

for table in m.Base.metadata.tables.values():
    for column in table.columns:
        if isinstance(column.type, JSONB):
            column.type = JSON()


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(m.Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_and_get_agent_os(client):
    create_resp = await client.post(
        "/api/v1/agent-os",
        json={"code": "enterprise", "name": "Enterprise", "enabled": True},
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["code"] == "enterprise"

    get_resp = await client.get(f"/api/v1/agent-os/{body['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Enterprise"


@pytest.mark.asyncio
async def test_create_duplicate_agent_os_code_returns_409(client):
    payload = {"code": "enterprise", "name": "Enterprise", "enabled": True}
    first = await client.post("/api/v1/agent-os", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/agent-os", json=payload)
    assert second.status_code == 409
    assert second.json()["error_code"] == "conflict"


@pytest.mark.asyncio
async def test_get_nonexistent_agent_os_returns_404(client):
    import uuid

    resp = await client.get(f"/api/v1/agent-os/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "not_found"


@pytest.mark.asyncio
async def test_full_hierarchy_creation_flow(client):
    agent_os_resp = await client.post(
        "/api/v1/agent-os", json={"code": "enterprise", "name": "Enterprise", "enabled": True}
    )
    agent_os_id = agent_os_resp.json()["id"]

    team_resp = await client.post(
        "/api/v1/teams",
        json={"agent_os_id": agent_os_id, "code": "sales", "name": "Sales", "enabled": True},
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    agent_resp = await client.post(
        "/api/v1/agents",
        json={"team_id": team_id, "code": "lead-qualifier", "name": "Lead Qualifier", "enabled": True},
    )
    assert agent_resp.status_code == 201
    assert agent_resp.json()["team_id"] == team_id


@pytest.mark.asyncio
async def test_capability_resolution_endpoint(client):
    agent_os_resp = await client.post(
        "/api/v1/agent-os", json={"code": "enterprise", "name": "Enterprise", "enabled": True}
    )
    agent_os_id = agent_os_resp.json()["id"]
    team_resp = await client.post(
        "/api/v1/teams", json={"agent_os_id": agent_os_id, "code": "sales", "name": "Sales", "enabled": True}
    )
    team_id = team_resp.json()["id"]
    agent_resp = await client.post(
        "/api/v1/agents", json={"team_id": team_id, "code": "bot", "name": "Bot", "enabled": True}
    )
    agent_id = agent_resp.json()["id"]

    await client.post(
        "/api/v1/capabilities/assignments",
        json={"level": "agent_os", "target_id": agent_os_id, "capability_codes": ["crm.customer.create"]},
    )
    await client.post(
        "/api/v1/capabilities/assignments",
        json={"level": "team", "target_id": team_id, "capability_codes": ["crm.customer.create"]},
    )
    await client.post(
        "/api/v1/capabilities/assignments",
        json={"level": "agent", "target_id": agent_id, "capability_codes": ["crm.customer.create"]},
    )

    resolve_resp = await client.post(
        "/api/v1/capabilities/resolve",
        json={"agent_os_id": agent_os_id, "team_id": team_id, "agent_id": agent_id},
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["effective_capabilities"] == ["crm.customer.create"]


@pytest.mark.asyncio
async def test_delete_agent_os_is_soft_delete(client):
    create_resp = await client.post(
        "/api/v1/agent-os", json={"code": "enterprise", "name": "Enterprise", "enabled": True}
    )
    agent_os_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/agent-os/{agent_os_id}")
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/agent-os/{agent_os_id}")
    assert get_resp.status_code == 404  # soft-deleted, hidden from default GET
