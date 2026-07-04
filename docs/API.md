# API Reference

Base path: `/api/v1`. Full interactive docs at `/docs` (Swagger UI) or
`/redoc` once the service is running.

All list endpoints accept `page` (default 1) and `page_size` (default
50, max 200) query parameters and return:

```json
{
  "items": [...],
  "total": 123,
  "page": 1,
  "page_size": 50,
  "has_next": true
}
```

All error responses share this shape:

```json
{
  "error_code": "not_found",
  "message": "AgentOS with id=... not found",
  "details": {},
  "correlation_id": "..."
}
```

| error_code | HTTP status |
|---|---|
| `not_found` | 404 |
| `conflict` | 409 |
| `validation_failed` | 422 |
| `capability_resolution_failed` | 422 |
| `mcp_gateway_error` | 502 |
| `runtime_execution_failed` | 500 |

---

## AgentOS — `/agent-os`

| Method | Path | Notes |
|---|---|---|
| GET | `/agent-os` | List (paginated) |
| POST | `/agent-os` | `code` must be unique; 409 on duplicate |
| GET | `/agent-os/{id}` | |
| PUT | `/agent-os/{id}` | Partial update |
| DELETE | `/agent-os/{id}` | Soft delete |

```json
// POST /api/v1/agent-os
{
  "code": "enterprise",
  "name": "Enterprise",
  "description": "Primary enterprise AgentOS",
  "default_model_id": null,
  "shared_prompt_id": null,
  "enabled": true
}
```

## Teams — `/teams`

| Method | Path | Notes |
|---|---|---|
| GET | `/teams?agent_os_id=` | Optional filter |
| POST | `/teams` | `(agent_os_id, code)` unique |
| GET | `/teams/{id}` | |
| PUT | `/teams/{id}` | |
| DELETE | `/teams/{id}` | Soft delete |

```json
// POST /api/v1/teams
{ "agent_os_id": "...", "code": "sales", "name": "Sales", "enabled": true }
```

## Agents — `/agents`

| Method | Path | Notes |
|---|---|---|
| GET | `/agents?team_id=` | Optional filter |
| POST | `/agents` | `(team_id, code)` unique |
| GET | `/agents/{id}` | |
| PUT | `/agents/{id}` | |
| DELETE | `/agents/{id}` | Soft delete |

```json
// POST /api/v1/agents
{
  "team_id": "...",
  "code": "lead-qualifier",
  "name": "Lead Qualifier",
  "prompt_id": null,
  "model_id": null,
  "temperature": 0.3,
  "enabled": true
}
```

## Prompts — `/prompts`

| Method | Path | Notes |
|---|---|---|
| GET | `/prompts?code=` | Optional filter |
| POST | `/prompts` | `version` auto-incremented per `code` |
| GET | `/prompts/{id}` | |
| PUT | `/prompts/{id}` | Cannot change `code`/`version` |
| DELETE | `/prompts/{id}` | Soft delete |

```json
// POST /api/v1/prompts
{
  "code": "sales-team",
  "name": "Sales Team Prompt",
  "content": "Focus on closing deals quickly while remaining honest about product limitations.",
  "status": "active"
}
```

## Skills — `/skills`

| Method | Path | Notes |
|---|---|---|
| GET | `/skills` | |
| POST | `/skills` | Includes `capability_codes` |
| GET | `/skills/{id}` | |
| PUT | `/skills/{id}` | |
| DELETE | `/skills/{id}` | Soft delete |
| GET | `/skills/{id}/agents` | Every Agent this Skill is currently assigned to (paginated). Excludes soft-deleted agents. |
| GET | `/agents/{id}/skills` | Reverse direction: every Skill assigned to this Agent (not paginated - typically a small list) |
| POST | `/skills/assign` | `{agent_id, skill_id}` |
| POST | `/skills/unassign` | `{agent_id, skill_id}` |

```json
// POST /api/v1/skills
{
  "code": "customer-management",
  "name": "Customer Management",
  "description": "CRUD operations over CRM customer records",
  "instructions": "Always confirm the customer name before creating a record.",
  "capability_codes": ["crm.customer.create", "crm.customer.search"]
}
```

```json
// GET /api/v1/skills/{id}/agents
{
  "items": [
    { "id": "...", "code": "lead-qualifier", "name": "Lead Qualifier", "team_id": "...", "enabled": true, ... }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50,
  "has_next": false
}

```

## Capabilities — `/capabilities`

| Method | Path | Notes |
|---|---|---|
| GET | `/capabilities/assignments?level=&target_id=` | `level` ∈ `agent_os\|team\|agent` |
| POST | `/capabilities/assignments` | Replaces the full set for that level/target |
| POST | `/capabilities/resolve` | Computes the effective intersection |

```json
// POST /api/v1/capabilities/assignments
{ "level": "team", "target_id": "...", "capability_codes": ["crm.customer.create", "crm.customer.search"] }

// POST /api/v1/capabilities/resolve
{ "agent_os_id": "...", "team_id": "...", "agent_id": "..." }
// ->
{
  "agent_os_capabilities": ["crm.customer.create", "erp.invoice.create"],
  "team_capabilities": ["crm.customer.create", "crm.customer.search"],
  "agent_capabilities": ["crm.customer.create"],
  "effective_capabilities": ["crm.customer.create"]
}
```

## Model Registry — `/models`

| Method | Path | Notes |
|---|---|---|
| GET | `/models` | |
| POST | `/models` | `(provider, model)` unique |
| GET | `/models/{id}` | |
| PUT | `/models/{id}` | |
| DELETE | `/models/{id}` | Soft delete |

```json
// POST /api/v1/models
{ "provider": "openai", "model": "gpt-4o-mini", "temperature": 0.7, "max_tokens": 4096, "enabled": true }
```

Supported `provider` values out of the box: `openai`, `anthropic`.

## Chat — `/chat`

### `POST /chat`

```json
// POST /api/v1/chat
{
  "agentOs": "enterprise",
  "team": "sales",
  "agent": "lead-qualifier",   // optional - omit to use the first enabled agent in the team
  "message": "Create customer ABC",
  "session_id": null,           // optional - omit to start a new session
  "user_id": "user-123"         // optional - used for memory scoping AND session ownership
}
```

**Session ownership:** if `session_id` is provided and doesn't exist yet,
it is created using exactly that ID, attributed to the request's
`user_id` - useful for clients that mint their own conversation ID
before the first message. If `session_id` already exists, it is only
resumed when its stored `user_id` matches the request's `user_id`
exactly (including `None` matching `None` for anonymous chats); a
mismatch returns `404 not_found` rather than resuming someone else's
conversation.

**Automatic memory:** when `user_id` is provided, after the run
completes Agno's own agentic memory (an LLM call) decides what - if
anything - from this turn is worth remembering long-term, and persists
it directly into `agent_memories` (queryable via `GET
/api/v1/agents/{id}/memories`). This happens automatically on every
turn that has a `user_id`; there is no separate "save memory" call to
make. See `docs/Architecture.md#8-memory`.

Response:

```json
{
  "session_id": "...",
  "run_id": "...",
  "agent_os": "enterprise",
  "team": "sales",
  "agent": "lead-qualifier",
  "message": "I've created customer ABC in the CRM.",
  "status": "completed"
}
```

Send `Authorization: Bearer <token>` or `X-API-Key: <key>` on this
request — it is forwarded unchanged to MCP Gateway for every tool call
made during this turn. This endpoint performs no authorization itself.

### `POST /chat/stream`

Same request body. Response is `text/event-stream` (SSE). Example event
stream:

```
event: agent_started
data: {"run_id": "...", "session_id": "...", "data": {"agent": "lead-qualifier", "team": "sales"}}

event: tool_selected
data: {"run_id": "...", "session_id": "...", "data": {"agno_event": "ToolCallStarted", "tools": [...]}}

event: tool_call_completed
data: {"run_id": "...", "session_id": "...", "data": {"capability_code": "crm.customer.create", "ok": true}}

event: agent_response
data: {"run_id": "...", "session_id": "...", "data": {"content": "I've created customer ABC..."}}

event: agent_completed
data: {"run_id": "...", "session_id": "...", "data": {"message": "I've created customer ABC in the CRM."}}
```

## Sessions — `/sessions`

| Method | Path | Notes |
|---|---|---|
| GET | `/sessions?user_id=` | **Always pass `user_id`** when acting on behalf of a specific end-user - omitting it returns sessions across ALL users, since Agno Runtime performs no authorization itself |
| GET | `/sessions/{id}?user_id=` | If `user_id` is passed and doesn't match the session's owner, returns `404` (not `403`) rather than confirming the session exists under a different owner. Omitting `user_id` returns the session regardless of owner. Includes full message history |

## Runs — `/runs`

| Method | Path | Notes |
|---|---|---|
| GET | `/runs?session_id=` | |
| GET | `/runs/{id}` | |
| GET | `/runs/{id}/events` | Full event timeline (array) |
| GET | `/runs/{id}/stream` | SSE; tails events, closes when run reaches a terminal status |

## Memories — `/memories`, `/agents/{id}/memories`

Memories are written **automatically** by Agno's own agentic memory
after each chat turn that includes a `user_id` - there is no `POST`
endpoint to create one manually. See `docs/Architecture.md#8-memory`.

| Method | Path | Notes |
|---|---|---|
| GET | `/memories?agent_id=` | |
| GET | `/agents/{agent_id}/memories` | |
| DELETE | `/memories/{id}` | Hard delete (memory is explicitly forgettable) |

## Workflows — `/workflows`

Sequential AI workflow orchestration over existing Agent/Team execution
- not a BPM engine, no branching/loops/parallel/approval. See
[`docs/Workflow.md`](Workflow.md) for the full architecture.

| Method | Path | Notes |
|---|---|---|
| GET | `/workflows?agent_os_id=` | |
| POST | `/workflows` | `steps` resolved from `agentCode`/`teamCode` to ids server-side |
| GET | `/workflows/{id}` | Includes resolved `steps` |
| PUT | `/workflows/{id}` | `steps` (if provided) replaces the whole sequence |
| DELETE | `/workflows/{id}` | Soft delete |
| POST | `/workflows/{id}/run` | Executes all steps sequentially |
| POST | `/workflows/{id}/run/stream` | SSE variant |

```json
// POST /api/v1/workflows
{
  "agent_os_id": "...",
  "code": "contract_review",
  "name": "Contract Review",
  "steps": [
    { "type": "AGENT", "agentCode": "retrieval_agent" },
    { "type": "AGENT", "agentCode": "legal_agent" },
    { "type": "TEAM", "teamCode": "risk_review_team" },
    { "type": "AGENT", "agentCode": "summary_agent" }
  ]
}

// POST /api/v1/workflows/{id}/run
{ "input": "Analyze HR leave policy" }
// ->
{ "workflowRunId": "...", "status": "COMPLETED", "result": "..." }
```

Same auth-propagation contract as `/chat`: inbound `Authorization`/
`X-API-Key` is forwarded unchanged to MCP Gateway for every tool call
any step's underlying Agent/Team makes.

## Workflow Runs — `/workflow-runs`

| Method | Path | Notes |
|---|---|---|
| GET | `/workflow-runs?workflow_id=` | |
| GET | `/workflow-runs/{id}` | |
| GET | `/workflow-runs/{id}/steps` | Per-step status/input/output |
| GET | `/workflow-runs/{id}/events` | `WorkflowStarted`/`WorkflowStepStarted`/`WorkflowStepCompleted`/`WorkflowCompleted`/`WorkflowFailed` |

## Observability

| Method | Path |
|---|---|
| GET | `/health` |
| GET | `/ready` |
| GET | `/version` |
