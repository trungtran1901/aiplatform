from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Non-streaming chat turn.

    Request shape:
        {
          "agentOs": "enterprise",
          "team": "sales",
          "message": "Create customer ABC"
        }

    The runtime resolves AgentOS -> Team -> Agent, composes the final
    prompt, resolves the effective (intersected) capability set, builds
    the Agno tool catalog, and executes the agent. Any inbound
    Authorization / X-API-Key header is forwarded unchanged to MCP
    Gateway on every tool call - this endpoint performs no authorization
    of its own.
    """
    service = ChatService(db)
    result = await service.handle_chat(payload)
    return ChatResponse(**result)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Streaming chat turn via Server-Sent Events.

    Emits events as the agent progresses: agent_started, tool_selected,
    tool_call_started, tool_call_completed, agent_response (content
    chunks), agent_completed, and error. Frontends can render these as
    "Agent is searching customer", "Agent is calling workflow", etc.
    """
    service = ChatService(db)

    async def event_generator():
        async for event in service.handle_chat_stream(payload):
            yield {
                "event": event["event_type"],
                "data": json.dumps(
                    {
                        "run_id": str(event["run_id"]),
                        "session_id": str(event["session_id"]) if event["session_id"] else None,
                        "data": event["data"],
                    }
                ),
            }

    return EventSourceResponse(event_generator())
