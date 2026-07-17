"""Unit tests for PlanningEngineService (AgentX v2 Phase 8)."""
from __future__ import annotations

from app.core.config import get_settings
from app.planning.models import PlanStepTargetType
from app.planning.service import PlanningEngineService


def test_default_plan_is_single_step_when_flag_off(monkeypatch):
    monkeypatch.setenv("FEATURE_PLANNING_ENGINE", "false")
    get_settings.cache_clear()

    planner = PlanningEngineService()
    plan = planner.build_plan("hello", agent_os_code="ent", team_code="sales", agent_code=None)

    assert len(plan.steps) == 1
    assert plan.steps[0].target_type == PlanStepTargetType.team
    get_settings.cache_clear()


def test_explicit_steps_produce_multi_step_plan_when_enabled(monkeypatch):
    monkeypatch.setenv("FEATURE_PLANNING_ENGINE", "true")
    get_settings.cache_clear()

    planner = PlanningEngineService()
    plan = planner.build_plan(
        "multi",
        agent_os_code="ent",
        team_code=None,
        agent_code=None,
        explicit_steps=[{"agent_code": "retrieval"}, {"agent_code": "summary"}],
    )

    assert [s.agent_code for s in plan.steps] == ["retrieval", "summary"]
    get_settings.cache_clear()
