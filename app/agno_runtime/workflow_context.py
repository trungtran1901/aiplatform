"""
WorkflowContext.

State object carried through a Workflow run's sequential step execution.
Each step receives the context, reads the previous step's output (or the
original workflow input for step 1), and the executor records its
output back into stepResults before moving to the next step.

No step type other than AGENT/TEAM exists in Phase 1, and there is
deliberately no branching/looping/conditional logic anywhere in this
object - it is pure linear state threading.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class WorkflowContext:
    workflowRunId: uuid.UUID
    workflowId: uuid.UUID
    sessionId: uuid.UUID
    userId: str | None
    correlationId: str | None = None

    # Mutated as the engine resolves each step - reflects "whichever
    # agent/team is currently executing", not a fixed value for the
    # whole run, since each step may target a different agent/team.
    agentId: uuid.UUID | None = None
    teamId: uuid.UUID | None = None

    # Free-form key/value bag a future step could read/write via
    # step_config (not used by Phase 1's pure sequential AGENT/TEAM
    # steps, but kept per spec's WorkflowContext field list so the
    # shape is stable for Phase 2 extensions).
    variables: dict = field(default_factory=dict)

    # step_order -> output text produced by that step. Step N's input is
    # always stepResults[N-1] (or the original workflow input for step
    # 0) - see WorkflowRunner.
    stepResults: dict[int, str] = field(default_factory=dict)

    def previous_output(self, step_order: int, original_input: str) -> str:
        """Returns the input a step at `step_order` should receive: the
        immediately preceding step's output, or the workflow's original
        input if this is the first step."""
        if step_order == 0:
            return original_input
        return self.stepResults.get(step_order - 1, original_input)

    def record_result(self, step_order: int, output: str) -> None:
        self.stepResults[step_order] = output
