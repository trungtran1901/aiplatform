# Knowledge Skill Integration

Treats an external **Knowledge Platform** microservice as just another
pluggable Skill type (`skill_type=KNOWLEDGE`), never embedded directly
into `Agent`. The Knowledge Platform itself is not modified — this
runtime only extends its own Skill Engine to know how to *call* it.

```
Agent -> Skill Engine -> KnowledgeSkillExecutor -> Knowledge Platform
```

## Data model

`skills.skill_type` (new enum: `MCP | WORKFLOW | PROMPT | CUSTOM |
KNOWLEDGE`, default `MCP` for backward compatibility) and
`skills.config` (JSONB, executor-specific) — see
`alembic/versions/0007_knowledge_skills.py`.

For `skill_type=KNOWLEDGE`, `config` is validated against
`app.knowledge.models.KnowledgeSkillConfig`:

```json
{
  "knowledgeBaseUrl": "http://knowledge-platform:8080",
  "searchApi": "/api/v1/search",
  "collectionId": "a2317ab0-2dda-43ca-a392-d4316808319a",
  "agentId": "cb75a8f9-e275-47b5-b796-1f66cc29b94b",
  "embeddingModelCode": "Qwen/Qwen3-Embedding-0.6B",
  "topK": 15,
  "timeout": 30,
  "stream": false
}
```

`knowledgeBaseUrl` is **per-Skill**, not global config, because
multiple Knowledge Platform instances may exist side by side (prod /
test / department-specific) — each Knowledge Skill names exactly one.

## Modules (`app/knowledge/`)

| File | Responsibility |
|---|---|
| `models.py` | `KnowledgeSkillConfig`, `KnowledgeChunk`, `KnowledgeSearchResult` |
| `exceptions.py` | `KnowledgeServiceError` hierarchy (config / timeout / unavailable) |
| `client.py` | Raw async HTTP POST to `{knowledgeBaseUrl}{searchApi}`, auth-forwarding only |
| `mapper.py` | Raw JSON -> typed result -> "Knowledge Context" prompt text |
| `executor.py` | `KnowledgeSkillExecutor` — one Skill config in, one context string out, never raises |
| `service.py` | `KnowledgeSkillService` — Skill-id/Agent-id level orchestration, used by the engine and the test endpoint |

## Runtime integration

`AgnoRuntimeEngine._resolve_instructions()` (in
`app/agno_runtime/engine.py`) calls
`KnowledgeSkillService.execute_for_agent(agent_id, message)` before
building any Agno `Agent`/`Team` member, and prepends the rendered
"Knowledge Context" block to that member's `instructions`. The Agent
never sees `collectionId`, `knowledgeBaseUrl`, or any other Knowledge
Platform detail — only the resulting context text, indistinguishable
from any other prompt section. A failing Knowledge Skill never aborts
the run; it simply contributes no context (logged as a warning).

## Auth propagation

Exactly the same contract as MCP Gateway (see
`docs/Architecture.md#6-auth-propagation`): whatever `Authorization` /
`X-API-Key` header arrived on the inbound chat request is forwarded
verbatim to the Knowledge Platform by `KnowledgeClient`. No token is
generated, decoded, or validated by this runtime.

## Agent configuration

Agents only reference Skill codes — never Knowledge Platform details:

```json
{ "skills": ["hr_policy_search", "employee_search", "leave_management"] }
```

## API

Existing `/api/v1/skills` CRUD now accepts `skill_type` and `config`:

```json
POST /api/v1/skills
{
  "code": "hr_policy_search",
  "name": "HR Policy Search",
  "skill_type": "KNOWLEDGE",
  "description": "Search HR knowledge base",
  "config": { "knowledgeBaseUrl": "http://knowledge-platform:8080", "collectionId": "..." }
}
```

New: `POST /api/v1/skills/{id}/test`

```json
{ "query": "How many vacation days do I get?" }
// ->
{
  "skill_id": "...",
  "skill_code": "hr_policy_search",
  "ok": true,
  "context": "Knowledge Context\n----...",
  "chunk_count": 3,
  "latency_ms": 142,
  "error": null
}
```

## Error handling

| Failure | Behavior |
|---|---|
| Knowledge Platform unreachable | `KnowledgeUnavailableError` (502), caught by `KnowledgeSkillExecutor` -> `ok=false`, Agent run continues without this Skill's context |
| Timeout (`config.timeout`) | `KnowledgeTimeoutError` (504), same graceful degradation |
| Invalid/missing `config` | `KnowledgeConfigError` (422) at Skill create/update time (schema validation), or at execution time if config was edited to be invalid |

Nothing in this integration can crash an Agent run — see
`tests/unit/test_knowledge_skill.py`.

## Extensibility

`KnowledgeSkillConfig`/`KnowledgeSkillExecutor` are the only places that
know the Knowledge Platform's wire format. Future support for hybrid
search, reranking, multiple collections, streaming search, or citation
rendering is additive: new optional fields on `KnowledgeSkillConfig`,
new parsing branches in `mapper.py`, without touching `Agent`,
`Skill` CRUD, or `AgnoRuntimeEngine`'s call sites.
