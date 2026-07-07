from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.run_control import request_cancel
from app.models.run import RunStatus
from app.repositories.run_repository import AgentEventRepository, AgentRunRepository
from app.schemas.common import PaginatedResponse
from app.schemas.run import AgentEventRead, AgentRunRead

router = APIRouter(prefix="/runs", tags=["Runs"])

_TERMINAL_STATUSES = (RunStatus.completed, RunStatus.failed, RunStatus.cancelled)


@router.get("", response_model=PaginatedResponse[AgentRunRead])
async def list_runs(
    session_id: UUID | None = None,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentRunRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, session_id=session_id)
    return PaginatedResponse[AgentRunRead](
        items=[AgentRunRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.get("/{run_id}", response_model=AgentRunRead)
async def get_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = AgentRunRepository(db)
    obj = await repo.get_or_404(run_id)
    return AgentRunRead.model_validate(obj)


@router.get("/{run_id}/events", response_model=list[AgentEventRead])
async def list_run_events(run_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = AgentEventRepository(db)
    events = await repo.list_by_run(run_id)
    return [AgentEventRead.model_validate(e) for e in events]


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Requests that an in-flight run stop as soon as possible - the same
    role a "Stop generating" button plays in a chat UI. This returns
    immediately (202 Accepted): it only signals intent, it does not
    itself stop anything. Whichever runtime instance is actually
    streaming this run's events (app/services/chat_service.py::
    handle_chat_stream) checks for this signal once per streamed event
    and, on the next check, closes the underlying Agno stream and marks
    the run `cancelled` - typically within one model/tool-call chunk's
    worth of latency. Poll `GET /runs/{id}` or watch
    `GET /runs/{id}/stream` for status to become `cancelled`.

    No-ops harmlessly (no signal sent) if the run has already reached a
    terminal status. If the run isn't actually executing on any
    instance right now (e.g. the request that started it already
    disconnected), the signal is simply never read and expires unused -
    this endpoint performs no authorization of its own, same as every
    other endpoint in this runtime.
    """
    repo = AgentRunRepository(db)
    run = await repo.get_or_404(run_id)

    if run.status in _TERMINAL_STATUSES:
        return {"run_id": str(run_id), "status": run.status.value, "cancel_requested": False}

    await request_cancel(str(run_id))
    return {"run_id": str(run_id), "status": run.status.value, "cancel_requested": True}


@router.get("/{run_id}/stream")
async def stream_run_events(run_id: UUID, db: AsyncSession = Depends(get_db)):
    """SSE endpoint that tails agent_events for a run.

    Useful for reconnecting to observe a run already in progress (started
    via /chat/stream from another client), or for replaying a completed
    run's event timeline. Polls the DB at a short interval rather than
    holding an in-memory pubsub channel, since events are already
    durably persisted by RunTrackingService - this keeps the runtime
    stateless and horizontally scalable.
    """
    settings = get_settings()
    event_repo = AgentEventRepository(db)
    run_repo = AgentRunRepository(db)

    async def event_generator():
        seen_ids: set[str] = set()
        while True:
            run = await run_repo.get(run_id)
            if run is None:
                yield {"event": "error", "data": json.dumps({"error": "run not found"})}
                return

            events = await event_repo.list_by_run(run_id)
            for event in events:
                if str(event.id) in seen_ids:
                    continue
                seen_ids.add(str(event.id))
                yield {
                    "event": event.event_type.value,
                    "data": json.dumps(
                        {
                            "id": str(event.id),
                            "run_id": str(event.run_id),
                            "event_type": event.event_type.value,
                            "payload": event.payload,
                            "created_at": event.created_at.isoformat(),
                        }
                    ),
                }

            if run.status.value in ("completed", "failed", "cancelled"):
                yield {"event": "stream_closed", "data": json.dumps({"status": run.status.value})}
                return

            await asyncio.sleep(settings.SSE_KEEPALIVE_SECONDS / 5 or 1)

    return EventSourceResponse(event_generator())