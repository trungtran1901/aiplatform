"""Unit tests for ContextEngineService (AgentX v2 Phase 2).

Pins down the two critical safety properties: (1) the block is always
"" when the feature flag is off, regardless of input, and (2) when on,
it assembles present fields and gracefully skips absent ones."""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.uicontext.service import ContextEngineService

pytestmark = pytest.mark.asyncio


async def test_returns_empty_string_when_feature_disabled(db_session, monkeypatch):
    monkeypatch.setenv("FEATURE_CONTEXT_ENGINE", "false")
    get_settings.cache_clear()

    service = ContextEngineService(db_session)
    result = await service.build_context_block({"applicationId": "hr", "pageId": "leave-page"})
    assert result == ""
    get_settings.cache_clear()


async def test_returns_empty_string_when_context_is_none(db_session, monkeypatch):
    monkeypatch.setenv("FEATURE_CONTEXT_ENGINE", "true")
    get_settings.cache_clear()

    service = ContextEngineService(db_session)
    result = await service.build_context_block(None)
    assert result == ""
    get_settings.cache_clear()


async def test_assembles_present_fields_when_enabled(db_session, monkeypatch):
    monkeypatch.setenv("FEATURE_CONTEXT_ENGINE", "true")
    get_settings.cache_clear()

    service = ContextEngineService(db_session)
    result = await service.build_context_block(
        {
            "applicationId": "hr-app",
            "pageId": "leave-page",
            "route": "/hr/leave",
            "currentRecord": {"id": "lr-1", "status": "pending"},
            "selectedItems": ["lr-1"],
        }
    )

    assert "Runtime Context" in result
    assert "hr-app" in result
    assert "leave-page" in result
    assert "lr-1" in result
    get_settings.cache_clear()
