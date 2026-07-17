"""Integration tests for the UI Metadata Registry (AgentX v2 Phase 1).
Verifies: feature-flag gating (404 when off), versioning-on-update
semantics, and latest-version resolution - the three behaviors the
Context Engine depends on."""
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
async def test_returns_404_when_feature_flag_disabled(client, monkeypatch):
    monkeypatch.setenv("FEATURE_UI_METADATA_REGISTRY", "false")
    get_settings.cache_clear()
    resp = await client.get("/api/v1/ui-metadata")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_and_get_latest_when_enabled(client, monkeypatch):
    monkeypatch.setenv("FEATURE_UI_METADATA_REGISTRY", "true")
    get_settings.cache_clear()

    create_resp = await client.post(
        "/api/v1/ui-metadata",
        json={
            "code": "employee-form",
            "kind": "FORM",
            "name": "Employee Form",
            "payload": {"fields": ["name", "email"]},
        },
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["version"] == 1

    latest = await client.get("/api/v1/ui-metadata/by-code/employee-form/latest")
    assert latest.status_code == 200
    assert latest.json()["payload"]["fields"] == ["name", "email"]


@pytest.mark.asyncio
async def test_update_creates_new_version_not_mutation(client, monkeypatch):
    monkeypatch.setenv("FEATURE_UI_METADATA_REGISTRY", "true")
    get_settings.cache_clear()

    create_resp = await client.post(
        "/api/v1/ui-metadata",
        json={"code": "leave-form", "kind": "FORM", "name": "Leave Form", "payload": {"fields": ["days"]}},
    )
    entry_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/ui-metadata/{entry_id}",
        json={"payload": {"fields": ["days", "reason"]}},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["version"] == 2

    # v1 must still exist untouched
    v1 = await client.get(f"/api/v1/ui-metadata/{entry_id}")
    assert v1.json()["payload"]["fields"] == ["days"]

    latest = await client.get("/api/v1/ui-metadata/by-code/leave-form/latest")
    assert latest.json()["version"] == 2
    assert latest.json()["payload"]["fields"] == ["days", "reason"]


@pytest.mark.asyncio
async def test_list_children_by_parent_code(client, monkeypatch):
    monkeypatch.setenv("FEATURE_UI_METADATA_REGISTRY", "true")
    get_settings.cache_clear()

    await client.post(
        "/api/v1/ui-metadata",
        json={"code": "hr-app", "kind": "APPLICATION", "name": "HR App", "payload": {}},
    )
    await client.post(
        "/api/v1/ui-metadata",
        json={
            "code": "leave-page",
            "kind": "PAGE",
            "name": "Leave Page",
            "parent_code": "hr-app",
            "payload": {},
        },
    )

    resp = await client.get("/api/v1/ui-metadata", params={"parent_code": "hr-app"})
    assert resp.status_code == 200
    codes = [i["code"] for i in resp.json()["items"]]
    assert codes == ["leave-page"]
