"""Event Engine API - AgentX v2 Phase 7, flagged.

Supports both application-emitted events (e.g. a frontend posting
"PageOpened"/"FieldChanged") and a polling SSE tail, following the exact
same polling-over-durable-storage pattern as GET /runs/{id}/stream
(app/api/v1/runs.py) rather than an in-memory pub/sub channel - keeps
this runtime stateless and horizontally scalable, same rationale.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.repositories.runtime_event_repository import RuntimeEventRepository
from app.schemas.common import PaginatedResponse
from app.schemas.runtime_event import RuntimeEventCreate, RuntimeEventRead

router = APIRouter(prefix="/runtime-events", tags=["Event Engine (v2, flagged)"])


def _require_enabled() -> None:
    if not get_settings().FEATURE_EVENT_ENGINE:
        raise NotFoundError("Event Engine is not enabled on this deployment")


@router.post("", response_model=RuntimeEventRead, status_code=status.HTTP_201_CREATED)
async def emit_runtime_event(payload: RuntimeEventCreate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = RuntimeEventRepository(db)
    obj = await repo.create(**payload.model_dump())
    return RuntimeEventRead.model_validate(obj)


@router.get("", response_model=PaginatedResponse[RuntimeEventRead])
async def list_runtime_events(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    repo = RuntimeEventRepository(db)
    items, total = await repo.list_by_entity(
        entity_type, entity_id, offset=pagination.offset, limit=pagination.limit
    )
    return PaginatedResponse[RuntimeEventRead](
        items=[RuntimeEventRead.model_validate(i) for i in items],
        total=total, page=pagination.page, page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.get("/stream")
async def stream_runtime_events(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    poll_interval_seconds: float = Query(default=2.0, ge=0.5, le=30.0),
    db: AsyncSession = Depends(get_db),
):
    """SSE tail for one entity's events - polls durable storage rather
    than holding an in-memory channel, same rationale as
    GET /runs/{id}/stream. Streams indefinitely; the client disconnects
    when done (there is no fixed terminal status for a generic entity
    the way there is for an AgentRun)."""
    _require_enabled()
    repo = RuntimeEventRepository(db)

    async def event_generator():
        seen_ids: set[str] = set()
        while True:
            events = await repo.list_by_entity(entity_type, entity_id, limit=200)
            for event in events:
                if str(event.id) in seen_ids:
                    continue
                seen_ids.add(str(event.id))
                yield {
                    "event": event.event_name,
                    "data": json.dumps(
                        {
                            "id": str(event.id),
                            "entity_type": event.entity_type,
                            "entity_id": event.entity_id,
                            "event_name": event.event_name,
                            "payload": event.payload,
                            "created_at": event.created_at.isoformat(),
                        }
                    ),
                }
            await asyncio.sleep(poll_interval_seconds)

    return EventSourceResponse(event_generator())
