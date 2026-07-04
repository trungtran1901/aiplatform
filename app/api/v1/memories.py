from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.repositories.memory_repository import AgentMemoryRepository
from app.schemas.common import PaginatedResponse
from app.schemas.memory import AgentMemoryRead

router = APIRouter(tags=["Memories"])


@router.get("/memories", response_model=PaginatedResponse[AgentMemoryRead])
async def list_memories(
    agent_id: UUID | None = None,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentMemoryRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, agent_id=agent_id)
    return PaginatedResponse[AgentMemoryRead](
        items=[AgentMemoryRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.get("/agents/{agent_id}/memories", response_model=PaginatedResponse[AgentMemoryRead])
async def list_agent_memories(
    agent_id: UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentMemoryRepository(db)
    items, total = await repo.list_by_agent(agent_id, offset=pagination.offset, limit=pagination.limit)
    return PaginatedResponse[AgentMemoryRead](
        items=[AgentMemoryRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = AgentMemoryRepository(db)
    obj = await repo.get_or_404(memory_id)
    await repo.hard_delete(obj)
