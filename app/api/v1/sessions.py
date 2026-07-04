from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.exceptions import NotFoundError
from app.repositories.session_repository import ChatSessionRepository
from app.schemas.common import PaginatedResponse
from app.schemas.session import ChatSessionDetail, ChatSessionRead

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("", response_model=PaginatedResponse[ChatSessionRead])
async def list_sessions(
    user_id: str | None = Query(
        default=None,
        description="Filter to sessions belonging to this user_id. Strongly "
        "recommended to always pass this - omitting it returns sessions "
        "across ALL users, since Agno Runtime itself performs no "
        "authorization (see MCP Gateway). Callers (e.g. a future Quasar "
        "Admin UI acting on a logged-in user's behalf) should always supply "
        "the caller's own user_id here.",
    ),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = ChatSessionRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, user_id=user_id)
    return PaginatedResponse[ChatSessionRead](
        items=[ChatSessionRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.get("/{session_id}", response_model=ChatSessionDetail)
async def get_session(
    session_id: UUID,
    user_id: str | None = Query(
        default=None,
        description="If provided, the session is only returned when its "
        "user_id matches - otherwise a 404 is returned even if the session "
        "exists, to avoid leaking another user's conversation history. "
        "Omitting this parameter returns the session regardless of owner; "
        "callers acting on behalf of a specific end-user should always "
        "supply it.",
    ),
    db: AsyncSession = Depends(get_db),
):
    repo = ChatSessionRepository(db)
    obj = await repo.get_with_messages(session_id, user_id=user_id)
    if obj is None:
        raise NotFoundError(f"ChatSession {session_id} not found")
    return ChatSessionDetail.model_validate(obj)