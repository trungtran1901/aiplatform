"""
UIAction DSL - versioned, strongly typed, serializable.

DSL_VERSION follows simple integer versioning: a frontend SDK checks
`action.dslVersion` and can choose to ignore/degrade unknown future
action types rather than crash - this is the "future-proof, backward
compatible" requirement from the spec. New ActionType values are
additive (append to the enum); existing ones are never renamed or
removed once shipped.

Nothing in this module executes anything - it is pure data shape. The
(future) frontend AgentX UI SDK is the only thing that turns a
UIActionPlan into real DOM/component mutations.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

DSL_VERSION = 1


class ActionType(str, Enum):
    """Mirrors the spec's UI Skill examples 1:1. Append-only."""

    fill_form = "FILL_FORM"
    set_value = "SET_VALUE"
    select_value = "SELECT_VALUE"
    click_button = "CLICK_BUTTON"
    navigate = "NAVIGATE"
    open_dialog = "OPEN_DIALOG"
    close_dialog = "CLOSE_DIALOG"
    upload_file = "UPLOAD_FILE"
    download_file = "DOWNLOAD_FILE"
    focus_component = "FOCUS_COMPONENT"
    highlight_component = "HIGHLIGHT_COMPONENT"
    expand_tree = "EXPAND_TREE"
    collapse_tree = "COLLAPSE_TREE"
    refresh_grid = "REFRESH_GRID"
    validate_form = "VALIDATE_FORM"


class UIAction(BaseModel):
    """One atomic, semantic UI instruction. `target` is a UI Metadata
    Registry component code (never a CSS selector/XPath - the runtime
    never knows or cares about DOM structure, only the semantic
    identity of the thing being acted on)."""

    actionType: ActionType
    target: str = Field(..., description="UI Metadata component/field/page code this action applies to")
    businessMeaning: str | None = Field(default=None, description="Human-readable reason, for audit/observability")
    value: str | int | float | bool | dict | list | None = Field(default=None)
    reason: str | None = Field(default=None, description="Why the agent chose this action")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    executionOrder: int = Field(default=0, description="Relative order among actions in the same plan")


class UIActionPlan(BaseModel):
    """A batch of UIActions produced for a single chat turn/run, handed
    to the frontend SDK to execute in `executionOrder`."""

    dslVersion: int = Field(default=DSL_VERSION)
    runId: str | None = None
    actions: list[UIAction] = Field(default_factory=list)

    def sorted_actions(self) -> list[UIAction]:
        return sorted(self.actions, key=lambda a: a.executionOrder)
