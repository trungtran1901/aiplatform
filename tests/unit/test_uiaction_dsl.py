"""Unit tests for the Action DSL (AgentX v2 Phase 4/5)."""
from __future__ import annotations

from app.uiaction.models import ActionType, UIAction, UIActionPlan


def test_actions_sort_by_execution_order():
    plan = UIActionPlan(
        actions=[
            UIAction(actionType=ActionType.set_value, target="leave.reason", value="vacation", executionOrder=1),
            UIAction(actionType=ActionType.click_button, target="leave.submit", executionOrder=0),
        ]
    )
    ordered = plan.sorted_actions()
    assert [a.actionType for a in ordered] == [ActionType.click_button, ActionType.set_value]


def test_plan_serializes_with_dsl_version():
    plan = UIActionPlan(actions=[UIAction(actionType=ActionType.navigate, target="leave-page")])
    dumped = plan.model_dump()
    assert dumped["dslVersion"] == 1
    assert dumped["actions"][0]["actionType"] == "NAVIGATE"
