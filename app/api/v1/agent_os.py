from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.exceptions import ConflictError
from app.repositories.hierarchy_repository import AgentOSRepository
from app.schemas.agent_os import AgentOSCreate, AgentOSRead, AgentOSUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/agent-os", tags=["AgentOS"])


@router.get("", response_model=PaginatedResponse[AgentOSRead])
async def list_agent_os(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentOSRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit)
    return PaginatedResponse[AgentOSRead](
        items=[AgentOSRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=AgentOSRead, status_code=status.HTTP_201_CREATED)
async def create_agent_os(payload: AgentOSCreate, db: AsyncSession = Depends(get_db)):
    repo = AgentOSRepository(db)
    existing = await repo.get_by_code(payload.code)
    if existing is not None:
        raise ConflictError(f"AgentOS with code '{payload.code}' already exists")
    obj = await repo.create(**payload.model_dump())
    return AgentOSRead.model_validate(obj)


@router.get("/{agent_os_id}", response_model=AgentOSRead)
async def get_agent_os(agent_os_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = AgentOSRepository(db)
    obj = await repo.get_or_404(agent_os_id)
    return AgentOSRead.model_validate(obj)


@router.put("/{agent_os_id}", response_model=AgentOSRead)
async def update_agent_os(agent_os_id: UUID, payload: AgentOSUpdate, db: AsyncSession = Depends(get_db)):
    repo = AgentOSRepository(db)
    obj = await repo.get_or_404(agent_os_id)
    obj = await repo.update(obj, **payload.model_dump(exclude_unset=True))
    return AgentOSRead.model_validate(obj)


@router.delete("/{agent_os_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_os(agent_os_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = AgentOSRepository(db)
    obj = await repo.get_or_404(agent_os_id)
    await repo.soft_delete(obj)
