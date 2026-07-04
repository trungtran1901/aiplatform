"""
Shared pytest fixtures.

Tests run against an in-memory SQLite database via aiosqlite for speed
and zero external dependencies. Since our ORM models use
PostgreSQL-specific JSONB columns (for chat_sessions.context,
chat_messages.message_metadata, agent_events.payload), we patch those
columns to generic JSON for the SQLite test engine only - production
migrations and the real engine still use JSONB. This keeps the test
suite fast and dependency-free while exercising the real ORM mapping,
repository, and service logic.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models as m


def _patch_jsonb_for_sqlite() -> None:
    """Swap JSONB type to plain JSON on the few columns that use it, so
    metadata.create_all() works against SQLite in tests."""
    for table in m.Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


_patch_jsonb_for_sqlite()


@pytest_asyncio.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(m.Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(bind=async_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
