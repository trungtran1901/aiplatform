from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.hierarchy_repository import AgentOSRepository, TeamRepository
from app.schemas.common import PaginatedResponse
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate

router = APIRouter(prefix="/teams", tags=["Teams"])


@router.get("", response_model=PaginatedResponse[TeamRead])
async def list_teams(
    agent_os_id: UUID | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = TeamRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, agent_os_id=agent_os_id)
    return PaginatedResponse[TeamRead](
        items=[TeamRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(payload: TeamCreate, db: AsyncSession = Depends(get_db)):
    agent_os_repo = AgentOSRepository(db)
    agent_os = await agent_os_repo.get(payload.agent_os_id)
    if agent_os is None:
        raise NotFoundError(f"AgentOS {payload.agent_os_id} not found")

    team_repo = TeamRepository(db)
    existing = await team_repo.get_by_code(payload.agent_os_id, payload.code)
    if existing is not None:
        raise ConflictError(f"Team with code '{payload.code}' already exists under this AgentOS")

    obj = await team_repo.create(**payload.model_dump())
    return TeamRead.model_validate(obj)


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(team_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = TeamRepository(db)
    obj = await repo.get_or_404(team_id)
    return TeamRead.model_validate(obj)


@router.put("/{team_id}", response_model=TeamRead)
async def update_team(team_id: UUID, payload: TeamUpdate, db: AsyncSession = Depends(get_db)):
    repo = TeamRepository(db)
    obj = await repo.get_or_404(team_id)
    obj = await repo.update(obj, **payload.model_dump(exclude_unset=True))
    return TeamRead.model_validate(obj)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = TeamRepository(db)
    obj = await repo.get_or_404(team_id)
    await repo.soft_delete(obj)
