"""Execution Engine - AgentX Runtime v2 (Phase 9, flagged).

Executes an ExecutionPlan (app.planning.models) step by step, delegating
ALL actual LLM/tool execution to the existing AgnoRuntimeEngine - same
"contains no agent-execution logic of its own" contract as
app.agno_runtime.workflow_runner.WorkflowRunner, which this module
deliberately mirrors rather than duplicates. What it adds beyond
WorkflowRunner/WorkflowExecutor: per-step RETRY (via tenacity, already a
project dependency) and a persisted, queryable timeline for ad-hoc plans
that were never saved as Workflow metadata.

ROLLBACK is intentionally NOT implemented: generically rolling back an
arbitrary prior LLM/tool call (which may have already created a CRM
record, sent an email, etc. via MCP Gateway) has no safe, general
mechanism - only a specific business capability's own compensating
action could do that, and this runtime has zero business logic by
design (see docs/Architecture.md section 1). `on_step_failed` is the
documented extension point: a caller wanting rollback for a specific
plan can supply a callback that issues whatever compensating MCP calls
make sense for their domain.
"""
from __future__ import annotations
