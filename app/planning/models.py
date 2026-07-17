from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PlanStepTargetType(str, Enum):
    agent = "AGENT"
    team = "TEAM"


@dataclass
class PlanStep:
    """One step in an ExecutionPlan - same AGENT|TEAM duality as
    app.models.workflow.WorkflowStep, but resolved by human-facing
    agentOs/team/agent codes rather than stored ids, since a Plan is
    ad-hoc and never persisted as Workflow metadata."""

    target_type: PlanStepTargetType
    agent_os_code: str
    team_code: str | None = None
    agent_code: str | None = None
    step_input_template: str | None = None  # None => use previous step's output (or the original message for step 0)
    max_retries: int = 0
    order: int = 0


@dataclass
class ExecutionPlan:
    original_message: str
    steps: list[PlanStep] = field(default_factory=list)
    rationale: str = ""
