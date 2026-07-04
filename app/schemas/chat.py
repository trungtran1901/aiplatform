from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Matches spec:
    {
      "agentOs": "enterprise",
      "team": "sales",
      "message": "Create customer ABC"
    }
    agentOs/team are human-readable `code` values, not UUIDs, so the
    Quasar Admin UI and external callers never need to know internal IDs.
    """

    agentOs: str = Field(..., description="AgentOS.code")
    team: str | None = Field(default=None, description="Team.code (optional). Omit to let AgentOS auto-route to a Team")
    agent: str | None = Field(default=None, description="Optional Agent.code; if omitted, the first enabled agent in the team is used")
    message: str = Field(..., min_length=1)
    session_id: UUID | None = Field(default=None, description="Existing session to continue; if omitted a new session is created")
    user_id: str | None = Field(default=None, description="Caller-supplied end-user identifier, used for memory scoping")

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
