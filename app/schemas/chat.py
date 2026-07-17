from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class UIContextFields(BaseModel):
    """AgentX Runtime v2 - Extended Chat Context (Phase 2).

    Every field is optional and defaults to None/empty. Omitting all of
    these makes a request behave EXACTLY as it did before this class
    existed - old clients never need to know this exists. When present,
    the (flagged) Context Engine assembles them alongside conversation
    memory / session / knowledge context before the prompt is composed;
    when the Context Engine feature flag is off, these fields are
    accepted (so clients can start sending them early) but simply
    ignored by the runtime.
    """

    applicationId: str | None = Field(default=None, description="UI Metadata Registry Application code")
    pageId: str | None = Field(default=None, description="UI Metadata Registry Page code")
    schemaVersion: str | None = Field(default=None, description="UI metadata schema_version the client is using")
    uiState: dict | None = Field(default=None, description="Arbitrary current UI state snapshot")
    selectedItems: list[str] | None = Field(default=None, description="IDs of currently-selected records/rows")
    currentRecord: dict | None = Field(default=None, description="The business record currently open, if any")
    route: str | None = Field(default=None, description="Current frontend route/path")
    variables: dict | None = Field(default=None, description="Free-form session/runtime variables")
    attachments: list[dict] | None = Field(default=None, description="File/attachment references for this turn")
    locale: str | None = Field(default=None, description="e.g. 'en-US', 'vi-VN'")
    device: str | None = Field(default=None, description="e.g. 'desktop', 'mobile', 'tablet'")


class ChatRequest(BaseModel):
    """Matches spec:
    {
      "agentOs": "enterprise",
      "team": "sales",
      "message": "Create customer ABC"
    }
    agentOs/team are human-readable `code` values, not UUIDs, so the
    Quasar Admin UI and external callers never need to know internal IDs.

    AgentX v2 note: `uiContext` is new and entirely optional (default
    None). Existing callers that never set it see identical behavior to
    before this field was added - see UIContextFields docstring.
    """

    agentOs: str = Field(..., description="AgentOS.code")
    team: str | None = Field(default=None, description="Team.code (optional). Omit to let AgentOS auto-route to a Team")
    agent: str | None = Field(default=None, description="Optional Agent.code; if omitted, the first enabled agent in the team is used")
    message: str = Field(..., min_length=1)
    session_id: UUID | None = Field(default=None, description="Existing session to continue; if omitted a new session is created")
    user_id: str | None = Field(default=None, description="Caller-supplied end-user identifier, used for memory scoping")

    # --- AgentX Runtime v2 (optional, additive - see UIContextFields) ---
    uiContext: UIContextFields | None = Field(
        default=None,
        description="Optional Extended Chat Context (application/page/uiState/etc.) consumed by the "
        "Context Engine when FEATURE_CONTEXT_ENGINE is enabled; ignored otherwise.",
    )

    model_config = {
        "populate_by_name": True,
    }


class ChatResponse(BaseModel):
    session_id: UUID
    run_id: UUID
    agent_os: str
    team: str | None = None
    agent: str | None = None
    message: str
    status: str


class ChatStreamEvent(BaseModel):
    """Shape of each SSE event payload emitted on /chat/stream and
    /runs/{id}/stream."""

    event_type: str
    run_id: UUID
    session_id: UUID | None = None
    data: dict = Field(default_factory=dict)
