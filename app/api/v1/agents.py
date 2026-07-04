from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.api.v1._presenters import skill_to_read_model
from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.hierarchy_repository import AgentRepository, TeamRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate
from app.schemas.common import PaginatedResponse
from app.schemas.skill import SkillRead

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.get("", response_model=PaginatedResponse[AgentRead])
async def list_agents(
    team_id: UUID | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, team_id=team_id)
    return PaginatedResponse[AgentRead](
        items=[AgentRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, db: AsyncSession = Depends(get_db)):
    team_repo = TeamRepository(db)
    team = await team_repo.get(payload.team_id)
    if team is None:
        raise NotFoundError(f"Team {payload.team_id} not found")

    agent_repo = AgentRepository(db)
    existing = await agent_repo.get_by_code(payload.team_id, payload.code)
    if existing is not None:
        raise ConflictError(f"Agent with code '{payload.code}' already exists under this Team")

    obj = await agent_repo.create(**payload.model_dump())
    return AgentRead.model_validate(obj)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = AgentRepository(db)
    obj = await repo.get_or_404(agent_id)
    return AgentRead.model_validate(obj)


@router.put("/{agent_id}", response_model=AgentRead)
async def update_agent(agent_id: UUID, payload: AgentUpdate, db: AsyncSession = Depends(get_db)):
    repo = AgentRepository(db)
    obj = await repo.get_or_404(agent_id)
    obj = await repo.update(obj, **payload.model_dump(exclude_unset=True))
    return AgentRead.model_validate(obj)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = AgentRepository(db)
    obj = await repo.get_or_404(agent_id)
    await repo.soft_delete(obj)


@router.get("/{agent_id}/skills", response_model=list[SkillRead])
async def list_agent_skills(agent_id: UUID, db: AsyncSession = Depends(get_db)):
    """Every Skill currently assigned to this Agent - the reverse
    direction of GET /skills/{id}/agents."""
    agent_repo = AgentRepository(db)
    await agent_repo.get_or_404(agent_id)  # 404s if the agent doesn't exist

    skill_repo = SkillRepository(db)
    skills = await skill_repo.list_skills_for_agent(agent_id)
    return [await skill_to_read_model(skill_repo, s) for s in skills]
