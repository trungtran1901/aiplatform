"""Unit tests pinning down the critical safety property shared by every
new v2 engine: disabled-by-default means a guaranteed no-op, not just a
documented intention."""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.events_v2.service import EventEngineService
from app.models.observation import ObservationType
from app.observation.service import ObservationEngineService

pytestmark = pytest.mark.asyncio


async def test_observation_record_is_noop_when_flag_off(db_session, monkeypatch):
    monkeypatch.setenv("FEATURE_OBSERVATION_ENGINE", "false")
    get_settings.cache_clear()
    service = ObservationEngineService(db_session)
    result = await service.record(ObservationType.warning, {"msg": "x"})
    assert result is None
    get_settings.cache_clear()


async def test_observation_record_persists_when_flag_on(db_session, monkeypatch):
    monkeypatch.setenv("FEATURE_OBSERVATION_ENGINE", "true")
    get_settings.cache_clear()
    service = ObservationEngineService(db_session)
    result = await service.record(ObservationType.warning, {"msg": "x"})
    assert result is not None
    get_settings.cache_clear()


async def test_event_emit_is_noop_when_flag_off(db_session, monkeypatch):
    monkeypatch.setenv("FEATURE_EVENT_ENGINE", "false")
    get_settings.cache_clear()
    service = EventEngineService(db_session)
    result = await service.emit("page", "p1", "PageOpened")
    assert result is None
    get_settings.cache_clear()


async def test_event_emit_persists_when_flag_on(db_session, monkeypatch):
    monkeypatch.setenv("FEATURE_EVENT_ENGINE", "true")
    get_settings.cache_clear()
    service = EventEngineService(db_session)
    result = await service.emit("page", "p1", "PageOpened")
    assert result is not None
    get_settings.cache_clear()
