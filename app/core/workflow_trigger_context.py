"""
Workflow trigger depth/cycle guard.

Uses ContextVar - the same task-scoped propagation pattern already used
by app.core.auth_context.PropagatedAuth - so the guard survives across
the fresh AgnoRuntimeEngine / WorkflowExecutionService instances each
nested workflow trigger creates (those are just Python objects created
per call; the ContextVar lives on the asyncio task, not on any one of
those objects).

Prevents:
  - Unbounded recursion (Workflow A's steps include an Agent whose
    WORKFLOW skill triggers Workflow A again, ad infinitum).
  - Direct or indirect cycles (A -> B -> A) even within the depth cap,
    since a workflow_code already in the current call chain is rejected
    outright, regardless of remaining depth budget.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from app.core.exceptions import RuntimeExecutionError

# Hard ceiling regardless of what any individual WorkflowSkillConfig
# requests via maxTriggerDepth - a per-skill config can only ever make
# the limit stricter, never looser, than this.
_MAX_GLOBAL_DEPTH = 5

_depth_var: ContextVar[int] = ContextVar("workflow_trigger_depth", default=0)
_visited_var: ContextVar[frozenset] = ContextVar("workflow_trigger_visited", default=frozenset())


@contextmanager
def enter_workflow_trigger(workflow_code: str, *, max_depth: int):
    """Context manager wrapping one nested workflow trigger attempt.
    Raises RuntimeExecutionError (caught by the tool wrapper in
    app.workflowskill.service and returned to the LLM as a normal tool
    result, never crashing the run) if the depth cap is exceeded or the
    workflow_code is already active in this call chain."""
    current_depth = _depth_var.get()
    visited = _visited_var.get()

    effective_max = min(max_depth, _MAX_GLOBAL_DEPTH)
    if current_depth >= effective_max:
        raise RuntimeExecutionError(
            f"Workflow trigger depth limit reached ({current_depth}/{effective_max}) "
            f"while attempting to trigger '{workflow_code}'"
        )
    if workflow_code in visited:
        raise RuntimeExecutionError(
            f"Cycle detected: workflow '{workflow_code}' is already running in this call chain"
        )

    depth_token = _depth_var.set(current_depth + 1)
    visited_token = _visited_var.set(visited | {workflow_code})
    try:
        yield
    finally:
        _depth_var.reset(depth_token)
        _visited_var.reset(visited_token)