# Agno Runtime Platform

A production-ready, metadata-driven agent orchestration runtime built on
[Agno](https://github.com/agno-agi/agno), FastAPI, PostgreSQL, and Redis.

## What this service is responsible for

- Agent Orchestration (AgentOS → Teams → Agents)
- Agent Management / Registry
- Team Management
- **AI Workflow Orchestration** (sequential Agent/Team chaining - see
  [`docs/Workflow.md`](docs/Workflow.md). Not a BPM engine, not n8n -
  no branching/loops/parallel/approval steps)
- Prompt Management (versioned, composable)
- Skill Management (reusable capability bundles)
- Session Management
- Memory Management
- Agent Observability (Runs, Events, SSE streaming)
- MCP Tool Discovery & Execution

## What this service is explicitly NOT responsible for

- RBAC / Authorization / Permission Enforcement
- **Business-process workflow execution** (branching, loops, parallel
  execution, human approval, BPM) - this runtime's own "Workflow" module
  is deliberately limited to linear AI orchestration; anything with
  business-process semantics belongs to n8n / a future BPM layer
  fronted by MCP Gateway
- ERP / CRM Integration

All of the above belong to **MCP Gateway**, a single external service
reachable at `POST {MCP_GATEWAY_URL}/execute`. This runtime forwards the
caller's `Authorization` / `X-API-Key` headers to MCP Gateway unchanged on
every tool call. It never inspects, decodes, or makes decisions based on
those credentials. See [`docs/Architecture.md`](docs/Architecture.md#auth-propagation)
for the full rationale.

## Quick start

```bash
cp .env.example .env
# edit .env: set OPENAI_API_KEY / ANTHROPIC_API_KEY, MCP_GATEWAY_URL, etc.

docker compose up --build
```

This starts:
- `postgres` (5432)
- `redis` (6379)
- `agno-runtime` (8080) — runs Alembic migrations automatically on boot, then serves the API

Visit `http://localhost:8080/docs` for interactive OpenAPI documentation.

## Project layout

```
app/
  api/v1/            FastAPI routers (one file per resource)
  agno_runtime/       Bridge between platform metadata and live Agno objects
    mcp_client.py      MCP-over-SSE client (auth-forwarding only)
    tool_adapter.py     Scopes an MCP session to a capability set at runtime
    memory_db.py         Bridges Agno's agentic memory to agent_memories
    engine.py            Resolves AgentOS/Team/Agent -> builds & runs Agno agents/teams
    workflow_context.py  Sequential workflow state object
    workflow_runner.py    Executes one workflow step via engine.run/run_team
    workflow_executor.py  The sequential orchestration loop over workflow steps
  core/                Settings, logging, exceptions, auth context, middleware
  db/                  SQLAlchemy async engine/session, declarative base + mixins
  models/              ORM models (21 tables, see docs/ERD.md)
  repositories/        Data-access layer (soft-delete-aware generic CRUD + custom queries)
  schemas/             Pydantic request/response DTOs
  services/            Business logic (capability resolution, prompt composition,
                       chat orchestration, run/event tracking, memory, workflow registry
                       + execution)
  observability/       /health, /ready, /version, OTel hooks
alembic/               Migrations (hand-authored, validated against ORM DDL)
tests/
  unit/                Capability resolution, prompt composition, MCP client,
                       tool adapter, workflow context/executor/runner - all isolated, no I/O
  integration/         Repository layer, workflow registry/execution, full FastAPI
                       request/response cycle
docs/
  Architecture.md       Full architecture writeup
  API.md                 Endpoint reference
  Development.md         Local dev workflow, testing, migrations
  Workflow.md             AI Workflow module: architecture, execution model, API
  ModelRegistry.md         Model registry: local/custom providers via base_url
  ERD.md                  Entity-relationship diagram (Mermaid)
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

Tests run against an in-memory SQLite database (no external services
required) and currently cover: capability intersection logic, prompt
composition, the MCP Gateway auth-forwarding contract, the dynamic tool
adapter, the repository layer, and full API request/response cycles.

## Key design invariant

```
Allowed Tools = intersection(
    agent_os_capabilities,
    team_capabilities,
    agent_capabilities ∪ skill_capabilities(agent)
)
```

No agent, prompt, skill, team, or tool definition is ever hardcoded.
Everything is created, read, updated, and deleted through the
`/api/v1/*` surfaces, ready for the Quasar Admin UI to consume.
