"""Integration tests for the Business Object Registry (AgentX v2 Phase 3)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models as m
from app.api.deps import get_db
from app.core.config import get_settings
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
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_404_when_disabled(client, monkeypatch):
    monkeypatch.setenv("FEATURE_BUSINESS_OBJECT_REGISTRY", "false")
    get_settings.cache_clear()
    resp = await client.get("/api/v1/business-objects")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_and_version_business_object(client, monkeypatch):
    monkeypatch.setenv("FEATURE_BUSINESS_OBJECT_REGISTRY", "true")
    get_settings.cache_clear()

    create_resp = await client.post(
        "/api/v1/business-objects",
        json={
            "code": "leave_request",
            "name": "Leave Request",
            "payload": {
                "fields": [{"name": "days", "type": "number", "required": True}],
                "relationships": [],
                "validation": [],
                "businessMeaning": "An employee's request for time off",
            },
        },
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["version"] == 1
    object_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/business-objects/{object_id}",
        json={"description": "Updated description"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2

    latest = await client.get("/api/v1/business-objects/by-code/leave_request/latest")
    assert latest.status_code == 200
    assert latest.json()["version"] == 2
