# Workflow Module

Sequential AI workflow orchestration over existing Agent/Team execution.
**Not** a BPM engine, **not** n8n - no branching, loops, parallel
execution, conditional logic, or human approval steps. Phase 1 supports
exactly one shape:

```
Step 1 -> Step 2 -> Step 3 -> ... -> Step N
```

Each step is either a single **Agent** or a full **Team**, addressed by
`agent_id`/`team_id`. A step's output becomes the next step's input. The
workflow's overall result is the last step's output.

## Architecture

```
AgentOS
  ├── Teams
  │     └── Agents
  ├── Workflows          <- new
  │     └── WorkflowSteps (AGENT | TEAM)
  ├── Memory
  ├── Sessions
  ├── MCP
  └── Audit
```

A `Workflow` belongs to exactly one `AgentOS` (same pattern as `Team`).
Each `WorkflowStep` references exactly one `Agent` or exactly one `Team`
by id - never both, enforced at the application layer
(`WorkflowRegistry`), not via a DB CHECK constraint (kept consistent
with the rest of this codebase's hand-authored, cross-dialect-portable
migrations).

### No duplicated execution logic

The Workflow engine adds **zero** new LLM/tool-calling code. It is a
pure orchestration loop over the *existing* `AgnoRuntimeEngine`:

```
app/agno_runtime/workflow_executor.py   - the sequential loop itself
app/agno_runtime/workflow_runner.py     - executes exactly one step,
                                           delegating to:
app/agno_runtime/engine.py              - AgnoRuntimeEngine.run() /
                                           .run_team()  (pre-existing for
                                           run(); .run_team()/.run_team_stream()
                                           and the by-id resolvers below
                                           are new additions made to
                                           support Workflow, since the
                                           runtime previously could only
                                           resolve an Agent by human-facing
                                           code, not by id, and had no
                                           Team execution at all)
```

### Gap that had to be filled: Team execution

Before this module, the runtime could execute a single `Agent` (via
`/api/v1/chat`) but had no way to execute a full `Team` (multiple
members coordinating via `agno.team.Team`). Since the spec requires
`step_type=TEAM` to work, `AgnoRuntimeEngine` gained:

- `resolve_context_by_id(agent_id)` - resolves an Agent (and its
  AgentOS/Team) directly by id, since Workflow steps store stable ids,
  not human-facing codes.
- `resolve_team_context_by_id(team_id)` - resolves every enabled member
  Agent of a Team, each via the same prompt-composition and
  capability-intersection logic a standalone chat turn would use - no
  new capability/prompt logic, just applied per-member.
- `run_team()` / `run_team_stream()` - builds a live `agno.team.Team`
  (`mode="coordinate"`) with every member fully constructed (model,
  prompt, MCP tools), executes it, and maps `TeamRunEvent`s onto the
  same `EventType` vocabulary single-agent runs use.

Teams have no `model_id` of their own in the existing schema (this was
**not** changed, per "DO NOT rewrite existing AgentOS architecture") -
the Team coordinator's model falls back to `AgentOS.default_model_id`,
same as any Agent that doesn't set its own `model_id`.

## Database

5 new tables (`alembic/versions/0004_workflows.py`):

| Table | Purpose | Delete semantics |
|---|---|---|
| `workflows` | Workflow metadata | Soft delete (`deleted_at`) - same as `teams`/`agents` |
| `workflow_steps` | Ordered AGENT/TEAM steps | Hard-cascaded with its Workflow |
| `workflow_runs` | One execution of a Workflow | Append-only (audit trail) |
| `workflow_run_steps` | One executed step within a run | Append-only |
| `workflow_events` | Observable occurrences during a run | Append-only |

`workflow_events` is a **separate table** from `agent_events`, not a
reuse of it - `agent_events.run_id` is scoped to a single `AgentRun`,
not a whole multi-step `WorkflowRun`, so overloading it would require
making `run_id` polymorphic. This is "reuse the existing event
mechanism" in the sense of reusing its *design* (append-only, FK'd to
its parent run, queryable + streamable), not its physical table.

See `docs/ERD.md` for the full diagram (not yet updated with these 5
tables - contributions welcome) and `alembic/versions/0004_workflows.py`
for the exact DDL, which was cross-validated column-by-column against
the SQLAlchemy ORM models the same way every other migration in this
repo was.

## Execution model

### WorkflowContext

Pure state object (`app/agno_runtime/workflow_context.py`) threaded
through every step:

```python
WorkflowContext(
    workflowRunId, workflowId, sessionId, userId, correlationId,
    agentId, teamId,      # mutated to reflect whichever agent/team is CURRENTLY executing
    variables,            # free-form bag, unused by Phase 1's pure linear steps
    stepResults,          # {step_order: output_text}
)
```

`context.previous_output(step_order, original_input)` returns step
N-1's output, or the workflow's original input if `step_order == 0`.

### WorkflowRunner

Executes exactly one step. `step_type=AGENT` →
`engine.resolve_context_by_id` + `engine.run`/`run_stream`.
`step_type=TEAM` → `engine.resolve_team_context_by_id` +
`engine.run_team`/`run_team_stream`. Sets `context.agentId`/`teamId`
before each call so a future step could inspect "who executed
previously" via the shared context.

### WorkflowExecutor

The orchestration loop: sorts steps by `step_order`, runs each via
`WorkflowRunner`, records each result into `WorkflowContext`, raises on
the first failure (no partial-success or skip-ahead semantics). Exposes
optional `on_step_started` / `on_step_completed` / `on_step_failed`
callbacks so a caller (`WorkflowExecutionService`) can persist
`WorkflowRunStep` records atomically as each step actually
starts/finishes - critical so that a later step's failure never
retroactively marks an already-completed earlier step as failed.

### WorkflowRegistry

Pure metadata CRUD (`app/services/workflow_registry.py`). Resolves each
step definition's human-facing `agentCode`/`teamCode` (matching the
spec's JSON example shape) into stable `agent_id`/`team_id`, scoped to
the Workflow's own `agent_os_id` - codes are only unique within an
AgentOS/Team, never globally. Step replacement is always wholesale
(`PUT` with a `steps` array replaces the entire sequence), matching the
same "replace, don't patch" pattern capability assignments use.

### WorkflowExecutionService

Top-level orchestrator for `POST /api/v1/workflows/{id}/run` (and its
streaming sibling), mirroring `ChatService`'s pattern: resolve metadata,
get-or-create a `chat_sessions` row (Workflow runs share the exact same
session table/ownership semantics as chat - see
`docs/Architecture.md#9-session-ownership`), create the `WorkflowRun`,
drive `WorkflowExecutor` through every step via its callbacks, persist
`WorkflowRunStep`/`WorkflowEvent` rows, mark the run completed/failed.

## Memory integration

Every step in a Workflow run shares the **same `session_id`** end to
end. Since Agno's own session-scoped context (and agentic memory, when
a `user_id` is present - see `docs/Architecture.md#8-memory`) is keyed
by `session_id`, this means later steps in a workflow can implicitly
see what earlier steps (and any earlier chat turns under that same
session) discussed, without the Workflow engine needing to thread
anything extra through `WorkflowContext.variables` itself.

## MCP integration

No changes to MCP Gateway or its contract. Each step's underlying
Agent/Team run opens its own MCP session scoped to its own
intersected capability set, exactly as a standalone chat turn would -
`WorkflowRunner` adds no MCP-related code of its own.

## API surface

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/workflows?agent_os_id=` | |
| POST | `/api/v1/workflows` | Body includes `agent_os_id` + `steps: [{type, agentCode\|teamCode, config}]` |
| GET | `/api/v1/workflows/{id}` | Includes resolved `steps` |
| PUT | `/api/v1/workflows/{id}` | `steps` (if provided) replaces the whole sequence |
| DELETE | `/api/v1/workflows/{id}` | Soft delete |
| POST | `/api/v1/workflows/{id}/run` | `{"input": "..."}` → `{"workflowRunId", "status", "result"}` |
| POST | `/api/v1/workflows/{id}/run/stream` | SSE: `WorkflowStarted`, `WorkflowStepStarted`, `WorkflowStep:<inner event>`, `WorkflowStepCompleted`, `WorkflowCompleted`, `WorkflowFailed` |
| GET | `/api/v1/workflow-runs?workflow_id=` | |
| GET | `/api/v1/workflow-runs/{id}` | |
| GET | `/api/v1/workflow-runs/{id}/steps` | |
| GET | `/api/v1/workflow-runs/{id}/events` | |

### Example: create + run

```json
POST /api/v1/workflows
{
  "agent_os_id": "...",
  "code": "contract_review",
  "name": "Contract Review",
  "steps": [
    {"type": "AGENT", "agentCode": "retrieval_agent"},
    {"type": "AGENT", "agentCode": "legal_agent"},
    {"type": "AGENT", "agentCode": "risk_agent"},
    {"type": "AGENT", "agentCode": "summary_agent"}
  ]
}
```

```json
POST /api/v1/workflows/{id}/run
{ "input": "Analyze HR leave policy" }

// ->
{ "workflowRunId": "...", "status": "COMPLETED", "result": "..." }
```

Same auth-propagation contract as `/api/v1/chat`: any inbound
`Authorization`/`X-API-Key` header is forwarded unchanged to MCP Gateway
on every tool call made by any step's underlying Agent/Team - this
endpoint performs no authorization of its own.

## What is deliberately NOT implemented

Per spec: branching, parallel execution, loop execution, human approval,
business-process workflows. Those belong to MCP Gateway / n8n / a future
BPM layer. `WorkflowStepType` has exactly two members (`AGENT`, `TEAM`)
and `WorkflowExecutor` has exactly one control-flow shape (linear,
stop-on-first-failure) - there is no code path anywhere in this module
that branches based on a step's output content.

## Testing

```
tests/unit/test_workflow_context.py          - state-threading contract
tests/unit/test_workflow_executor.py          - orchestration loop, callbacks
tests/unit/test_workflow_runner.py            - AGENT/TEAM routing to AgnoRuntimeEngine
tests/integration/test_workflow_registry.py    - CRUD, code resolution, step replacement
tests/integration/test_workflow_execution_service.py  - full DB-backed run lifecycle
tests/integration/test_workflows_api.py        - HTTP-level CRUD + run
```

All execution-path tests mock `AgnoRuntimeEngine.run`/`run_team` (no
real LLM/MCP needed) - they test orchestration correctness, not model
output.
