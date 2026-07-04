# Architecture

## 1. Scope boundary

Agno Runtime is a pure **agent orchestration** layer. It deliberately
excludes:

| Responsibility              | Owner          |
|------------------------------|----------------|
| RBAC / Authorization         | MCP Gateway    |
| Permission enforcement       | MCP Gateway    |
| Workflow execution           | MCP Gateway    |
| ERP / CRM integration        | MCP Gateway    |
| Agent orchestration          | **Agno Runtime** |
| Prompt / Skill / Team / Agent management | **Agno Runtime** |
| Session / Memory / Run / Event tracking  | **Agno Runtime** |
| MCP tool discovery & execution           | **Agno Runtime** (delegates the actual call to MCP Gateway) |

This separation means Agno Runtime can be redeployed, scaled, or even
swapped out without touching the authorization model, and MCP Gateway
can change its RBAC implementation without the runtime needing to know.

## 2. The Agno hierarchy

```
AgentOS
  └── Teams
        └── Agents
  └── Shared Resources (Prompts, Skills, Model Registry, Capability scope)
```

- **AgentOS** (`agent_os` table) is the top-level container — typically
  one row per product/tenant (`enterprise`, `retail-bot`, ...). It owns a
  `default_model_id` (fallback model for any Agent beneath it that
  doesn't specify its own) and a `shared_prompt_id` (organization-wide
  prompt section).
- **Team** (`teams` table) orchestrates a group of Agents. Maps directly
  onto Agno's own `Team` construct (`agno.team.Team`), which supports
  `mode="coordinate"` (the default we use) for genuine multi-agent
  collaboration when a team has more than one enabled agent.
- **Agent** (`agents` table) is the unit that actually reasons, calls
  tools, and uses memory. Maps onto `agno.agent.Agent`.

Every layer is metadata: created, updated, and deleted exclusively
through `/api/v1/agent-os`, `/api/v1/teams`, `/api/v1/agents`. No Python
code anywhere hardcodes a specific agent, team, or tenant.

## 3. Prompt composition

```
Final Runtime Prompt = AgentOS.shared_prompt + Team.team_prompt + Agent.prompt
```

Composition is **additive and sectioned**, not override-based. Each
level contributes a clearly labeled section
(`PromptCompositionService.compose`):

```
# Organization Context (enterprise)
<AgentOS prompt content>

# Team Context (sales)
<Team prompt content>

# Agent Instructions (lead-qualifier)
<Agent prompt content>
```

This lets the AgentOS define org-wide tone/constraints once, the Team
narrow into domain context, and the Agent specify precise task
instructions — without any level needing to know about or repeat the
others' content. Missing prompt assignments are simply omitted; the
service never raises just because a level has no prompt configured.

Prompts themselves are versioned (`prompts.version`, auto-incremented
per `code` on `POST /api/v1/prompts`) and have a `status` of `draft` /
`active` / `archived`. Composition only ever resolves a prompt by its
**id** (set on `AgentOS.shared_prompt_id` / `Team.team_prompt_id` /
`Agent.prompt_id`), so swapping which version is "live" for a given
code is a metadata operation, not a code change.

## 4. Capability resolution — the core invariant

```
effective_capabilities = intersection(
    agent_os_capabilities,
    team_capabilities,
    agent_capabilities ∪ skill_capabilities(agent)
)
```

Implemented in `app/services/capability_service.py`. Capability codes
are opaque strings whose only source of truth is MCP Gateway — this
runtime never validates that a capability code "exists," it only tracks
which codes are *assigned* at each of the three levels
(`agent_os_capabilities`, `team_capabilities`, `agent_capabilities`
tables) plus which codes are contributed by **Skills** assigned to an
Agent (`agent_skills` → `skill_capabilities`).

Using intersection (not union) means capability scope can only ever
*narrow* as you go from AgentOS → Team → Agent, which keeps the
"least-privilege by construction" property even though MCP Gateway is
the only thing that actually enforces anything. If `AgentOS` doesn't
grant a capability, no Team or Agent under it can ever use it,
regardless of what's assigned at lower levels.

`POST /api/v1/capabilities/resolve` exposes this computation directly so
the Quasar Admin UI can preview the effective tool set before saving an
assignment.

## 5. MCP Tool Adapter

```
Load Capabilities -> Build Tool Catalog -> Inject Tools Into Agent
```

`app/agno_runtime/tool_adapter.py`:

1. `ToolCatalogBuilder._load_schema_catalog()` calls MCP Gateway's
   (optional, best-effort) `GET /capabilities` discovery endpoint once
   per chat turn, to learn the real JSON Schema + description for each
   capability code, if the Gateway exposes one.
2. For each *effective* capability code (from step 4 above),
   `ToolCatalogBuilder.build()` constructs a real
   `agno.tools.function.Function` object — not a Python callable with a
   hand-written signature, since the parameter shape is only known at
   runtime. If no schema was discoverable, a generic
   `{"arguments": {...}}` passthrough schema is used so the LLM can still
   call the tool.
3. Each `Function.entrypoint` is a `DynamicToolEntrypoint` bound to one
   capability code. Calling it makes one `POST /execute` call to MCP
   Gateway and returns the JSON result (or error) as a string, which
   Agno feeds back into the LLM's context.

No tool is ever hardcoded in source code. The catalog is rebuilt from
scratch on every chat turn from current metadata.

## 6. Auth propagation

This is the most security-critical contract in the system.

- `app/core/middleware.py` (`RequestContextMiddleware`) reads
  `Authorization` and `X-API-Key` from the **inbound** HTTP request and
  stores them in a request-scoped `contextvars`-backed object
  (`app/core/auth_context.py::PropagatedAuth`). It never decodes a JWT,
  never checks a scope, never makes a true/false authorization decision.
- `app/agno_runtime/mcp_client.py::MCPGatewayClient._build_headers()`
  reads that same context and attaches the headers **verbatim** to every
  `POST {MCP_GATEWAY_URL}/execute` call.
- A `401`/`403` response from MCP Gateway is **not** raised as a Python
  exception anywhere in this codebase — it is returned as
  `{"ok": false, "status_code": 403, "body": {...}}` and surfaced to the
  LLM as a normal tool result (see `DynamicToolEntrypoint.__call__`),
  with a note clarifying that MCP Gateway made the call, not the
  runtime. Only genuine transport failures (timeouts, connection
  refusals, malformed responses) raise `MCPGatewayError`.

This means Agno Runtime has **zero authorization logic** anywhere in its
codebase — searching the repo for "role", "permission", or "scope"
checks against credentials will turn up nothing, by design.

## 7. Runtime flow — `POST /api/v1/chat`

```
1. Resolve AgentOS(code) -> Team(code) -> Agent(code | first-enabled)
2. Compose final prompt (sec. 3)
3. Resolve effective capabilities (sec. 4)
4. Build Agno tool catalog (sec. 5)
5. Get-or-create ChatSession
6. Create AgentRun (status=pending) + persist inbound ChatMessage
7. Mark run "running"
8. agno.agent.Agent(model=..., instructions=<final prompt>, tools=<catalog>).arun(message)
     - Agno's own reasoning loop selects and calls tools
     - Each tool call -> DynamicToolEntrypoint -> MCP Gateway /execute
       (auth headers forwarded per sec. 6)
9. Persist assistant ChatMessage, mark run "completed" (or "failed")
10. Persist AgentEvents throughout (agent_started, tool_call_started,
    tool_call_completed, agent_completed, error, ...)
```

`POST /api/v1/chat/stream` runs the same flow but yields Server-Sent
Events as Agno surfaces `RunResponseEvent`s
(`app/agno_runtime/engine.py::run_stream`), mapped onto the platform's
own `EventType` vocabulary so frontend consumers only need to know one
event taxonomy regardless of Agno's internal naming. `GET
/api/v1/runs/{id}/stream` lets a client reconnect and tail a run's event
timeline independently (polling the durable `agent_events` table rather
than holding an in-memory pub/sub channel — keeping the runtime
stateless and horizontally scalable).

## 8. Memory

Two distinct mechanisms, deliberately kept as one source of truth rather
than two:

- **Session continuity** (within a single conversation) is handled by
  Agno internally via `session_id` passed to `agno_agent.arun(...)` -
  this is not what the `agent_memories` table is for.
- **Cross-session, agentic memory** ("remember that I'm vegetarian",
  ChatGPT-memory style) is implemented with
  `agno.memory.v2.Memory(model=..., db=PlatformMemoryDb(agent_id))` and
  `Agent(enable_user_memories=True)` (see `app/agno_runtime/engine.py`).
  After every chat turn that has a `user_id`, Agno runs its own
  `MemoryManager` - an LLM call that decides what (if anything) is worth
  remembering from the conversation, then calls `add_memory` /
  `update_memory` / `delete_memory` as tool-calls. This happens
  automatically; no hand-written extraction logic exists in this
  codebase. Memory extraction is awaited before the run is considered
  complete (`await asyncio.gather(*tasks)` inside Agno), so by the time
  `POST /api/v1/chat` returns, any new memories are already durably
  persisted.
- **`PlatformMemoryDb`** (`app/agno_runtime/memory_db.py`) is a from-scratch
  implementation of Agno's `agno.memory.v2.db.base.MemoryDb` interface
  that reads/writes directly against `agent_memories` - the platform
  never lets Agno create or own a second, separate memory table. Each
  Agno-extracted memory's native `memory_id` is stored as
  `agent_memories.source_memory_id`, so re-extraction after later runs
  upserts the same row instead of duplicating it. The interface is
  synchronous by Agno's own design, so `PlatformMemoryDb` uses a small,
  dedicated sync SQLAlchemy engine (`DATABASE_URL_SYNC`) rather than
  bridging into the request's async session.
- Chat requests with no `user_id` skip agentic memory entirely (no
  `Memory`/`enable_user_memories` is configured) rather than writing
  anonymous, unattributable memories.
- `GET /api/v1/memories`, `GET /api/v1/agents/{id}/memories`, and
  `DELETE /api/v1/memories/{id}` are the platform's own read/delete APIs
  over the exact same rows Agno writes - there is no second copy to keep
  in sync. `memory_type` is one of `conversation | summary | fact |
  preference | working_memory`; agentically-extracted memories are
  currently always tagged `fact`.

## 9. Session ownership

`POST /api/v1/chat` accepts an optional `session_id`. Two distinct cases:

- **`session_id` doesn't exist yet** (e.g. a frontend that mints its own
  conversation ID before the first message is sent): the session is
  *created* using exactly that client-supplied ID, attributed to the
  request's `user_id`. The client's chosen ID remains the canonical
  reference for the conversation going forward - it is never rejected or
  silently swapped for a server-generated one.
- **`session_id` already exists**: `chat_service.py` only resumes it if
  the session's stored `user_id` matches the request's `user_id`
  *exactly* (including the anonymous case, `None` continuing `None`). A
  mismatch returns `404 not_found` rather than resuming a different
  user's conversation - which would also inherit that user's
  Agno-extracted memories and full message history.

The same ownership awareness applies to `GET /api/v1/sessions` and
`GET /api/v1/sessions/{id}`: both accept an optional `user_id` query
parameter; omitting it returns/looks up sessions across all users (Agno
Runtime performs no authorization itself - this is a data-scoping
convenience, not RBAC), so any caller acting on behalf of a specific
end-user must always pass it.

## 10. Soft delete strategy

All **metadata** tables (`agent_os`, `teams`, `agents`, `prompts`,
`skills`, `model_registry`) support soft delete via `deleted_at`,
because `agent_runs` / `chat_sessions` / `agent_events` hold foreign keys
into them for permanent audit/observability purposes — hard-deleting a
Team that has 10,000 historical runs would either cascade-delete
history or orphan it.

**Runtime/audit** tables (`chat_messages`, `agent_runs`, `agent_events`)
are append-only and never deleted by any API surface — they are the
permanent record of what happened.

**`agent_memories`** is the one exception that supports hard delete
(`DELETE /api/v1/memories/{id}`), since memory is explicitly designed to
be forgettable.

See [`ERD.md`](ERD.md) for the full schema diagram.

## 11. Observability

- `GET /health` — liveness (process up).
- `GET /ready` — readiness (DB reachable).
- `GET /version` — build/version info.
- Structured JSON logs (`structlog`) with a `correlation_id` bound via
  `contextvars` to every log line in a request, sourced from
  `X-Correlation-ID` or generated per-request.
- OpenTelemetry hooks (`app/observability/tracing.py`), disabled by
  default (`OTEL_ENABLED=false`), auto-instrumenting FastAPI when
  enabled.
- Every agent run's full event timeline is queryable
  (`GET /api/v1/runs/{id}/events`) or streamable
  (`GET /api/v1/runs/{id}/stream`), independent of whether the original
  `/chat/stream` client is still connected.