# Entity Relationship Diagram

This ERD reflects the schema created by `alembic/versions/0001_initial_schema.py`
and defined in `app/models/`. Render with any Mermaid-compatible viewer
(GitHub renders this natively).

```mermaid
erDiagram
    MODEL_REGISTRY {
        uuid id PK
        string provider
        string model
        float temperature
        int max_tokens
        bool enabled
        timestamp deleted_at
    }

    PROMPTS {
        uuid id PK
        string code
        string name
        text content
        int version
        enum status
        timestamp deleted_at
    }

    AGENT_OS {
        uuid id PK
        string code
        string name
        text description
        uuid default_model_id FK
        uuid shared_prompt_id FK
        bool enabled
        timestamp deleted_at
    }

    TEAMS {
        uuid id PK
        uuid agent_os_id FK
        string code
        string name
        text description
        uuid team_prompt_id FK
        bool enabled
        timestamp deleted_at
    }

    AGENTS {
        uuid id PK
        uuid team_id FK
        string code
        string name
        text description
        uuid prompt_id FK
        uuid model_id FK
        float temperature
        bool enabled
        timestamp deleted_at
    }

    SKILLS {
        uuid id PK
        string code
        string name
        text description
        text instructions
        timestamp deleted_at
    }

    SKILL_CAPABILITIES {
        uuid id PK
        uuid skill_id FK
        string capability_code
    }

    AGENT_SKILLS {
        uuid id PK
        uuid agent_id FK
        uuid skill_id FK
    }

    AGENT_OS_CAPABILITIES {
        uuid id PK
        uuid agent_os_id FK
        string capability_code
    }

    TEAM_CAPABILITIES {
        uuid id PK
        uuid team_id FK
        string capability_code
    }

    AGENT_CAPABILITIES {
        uuid id PK
        uuid agent_id FK
        string capability_code
    }

    CHAT_SESSIONS {
        uuid id PK
        uuid agent_os_id FK
        uuid team_id FK
        uuid agent_id FK
        string user_id
        string title
        jsonb context
        timestamp deleted_at
    }

    CHAT_MESSAGES {
        uuid id PK
        uuid session_id FK
        uuid run_id FK
        enum role
        text content
        jsonb message_metadata
    }

    AGENT_RUNS {
        uuid id PK
        uuid session_id FK
        uuid agent_id FK
        enum status
        text input
        text output
        text error_message
        timestamp started_at
        timestamp finished_at
    }

    AGENT_EVENTS {
        uuid id PK
        uuid run_id FK
        enum event_type
        jsonb payload
    }

    AGENT_MEMORIES {
        uuid id PK
        uuid agent_id FK
        string user_id
        enum memory_type
        text content
    }

    MODEL_REGISTRY ||--o{ AGENT_OS : "default_model"
    PROMPTS ||--o{ AGENT_OS : "shared_prompt"
    AGENT_OS ||--o{ TEAMS : "has"
    PROMPTS ||--o{ TEAMS : "team_prompt"
    TEAMS ||--o{ AGENTS : "has"
    PROMPTS ||--o{ AGENTS : "prompt"
    MODEL_REGISTRY ||--o{ AGENTS : "model"

    SKILLS ||--o{ SKILL_CAPABILITIES : "bundles"
    AGENTS ||--o{ AGENT_SKILLS : "assigned"
    SKILLS ||--o{ AGENT_SKILLS : "assigned_to"

    AGENT_OS ||--o{ AGENT_OS_CAPABILITIES : "scopes"
    TEAMS ||--o{ TEAM_CAPABILITIES : "scopes"
    AGENTS ||--o{ AGENT_CAPABILITIES : "scopes"

    AGENT_OS ||--o{ CHAT_SESSIONS : "scopes"
    TEAMS ||--o{ CHAT_SESSIONS : "scopes"
    AGENTS ||--o{ CHAT_SESSIONS : "scopes"
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : "contains"
    CHAT_SESSIONS ||--o{ AGENT_RUNS : "contains"
    AGENTS ||--o{ AGENT_RUNS : "executes"
    AGENT_RUNS ||--o{ CHAT_MESSAGES : "produces"
    AGENT_RUNS ||--o{ AGENT_EVENTS : "emits"
    AGENTS ||--o{ AGENT_MEMORIES : "owns"
```

## Notes

- **Soft delete** (`deleted_at`) applies to all metadata tables:
  `model_registry`, `prompts`, `agent_os`, `teams`, `agents`, `skills`.
  Runtime/audit tables (`chat_sessions` excluded, see below) do **not**
  soft-delete because they represent immutable history.
- `chat_sessions` *does* carry `deleted_at` (a session can be archived by
  an end user without losing the metadata trail), but `chat_messages`,
  `agent_runs`, and `agent_events` are append-only and never deleted -
  they are the permanent observability/audit trail for a run.
- `agent_memories` is deletable via `DELETE /api/v1/memories/{id}` (hard
  delete) since memory is explicitly mutable/forgettable by design.
- Capability assignment tables (`*_capabilities`) are pure association
  tables: no soft delete, replaced wholesale via `set_*_capabilities()`
  rather than incrementally patched, to keep the "current assignment"
  always queryable as one clean set per level.
