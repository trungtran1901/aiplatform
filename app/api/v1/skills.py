from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.api.v1._presenters import skill_to_read_model
from app.core.exceptions import ConflictError
from app.repositories.skill_repository import SkillRepository
from app.schemas.agent import AgentRead
from app.schemas.common import PaginatedResponse
from app.schemas.skill import AgentSkillAssign, SkillCreate, SkillRead, SkillUpdate

router = APIRouter(prefix="/skills", tags=["Skills"])


@router.get("", response_model=PaginatedResponse[SkillRead])
async def list_skills(pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)):
    repo = SkillRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit)
    read_items = [await skill_to_read_model(repo, i) for i in items]
    return PaginatedResponse[SkillRead](
        items=read_items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def create_skill(payload: SkillCreate, db: AsyncSession = Depends(get_db)):
    repo = SkillRepository(db)
    existing = await repo.get_by_code(payload.code)
    if existing is not None:
        raise ConflictError(f"Skill with code '{payload.code}' already exists")

    data = payload.model_dump(exclude={"capability_codes"})
    obj = await repo.create(**data)
    await repo.set_capability_codes(obj.id, payload.capability_codes)
    return await skill_to_read_model(repo, obj)


@router.get("/{skill_id}", response_model=SkillRead)
async def get_skill(skill_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = SkillRepository(db)
    obj = await repo.get_or_404(skill_id)
    return await skill_to_read_model(repo, obj)


@router.put("/{skill_id}", response_model=SkillRead)
async def update_skill(skill_id: UUID, payload: SkillUpdate, db: AsyncSession = Depends(get_db)):
    repo = SkillRepository(db)
    obj = await repo.get_or_404(skill_id)
    update_data = payload.model_dump(exclude_unset=True, exclude={"capability_codes"})
    obj = await repo.update(obj, **update_data)
    if payload.capability_codes is not None:
        await repo.set_capability_codes(obj.id, payload.capability_codes)
    return await skill_to_read_model(repo, obj)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = SkillRepository(db)
    obj = await repo.get_or_404(skill_id)
    await repo.soft_delete(obj)


@router.get("/{skill_id}/agents", response_model=PaginatedResponse[AgentRead])
async def list_skill_agents(
    skill_id: UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Every Agent this Skill is currently assigned to - answers
    "which agents have this skill?". The reverse direction of
    GET /agents/{id}/skills."""
    repo = SkillRepository(db)
    await repo.get_or_404(skill_id)  # 404s if the skill doesn't exist

    agents, total = await repo.list_agents_for_skill(
        skill_id, offset=pagination.offset, limit=pagination.limit
    )
    return PaginatedResponse[AgentRead](
        items=[AgentRead.model_validate(a) for a in agents],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("/assign", status_code=status.HTTP_201_CREATED)
async def assign_skill_to_agent(payload: AgentSkillAssign, db: AsyncSession = Depends(get_db)):
    repo = SkillRepository(db)
    await repo.get_or_404(payload.skill_id)  # validates skill exists
    await repo.assign_to_agent(payload.agent_id, payload.skill_id)
    return {"agent_id": str(payload.agent_id), "skill_id": str(payload.skill_id), "assigned": True}


@router.post("/unassign", status_code=status.HTTP_200_OK)
async def unassign_skill_from_agent(payload: AgentSkillAssign, db: AsyncSession = Depends(get_db)):
    repo = SkillRepository(db)
    await repo.unassign_from_agent(payload.agent_id, payload.skill_id)
    return {"agent_id": str(payload.agent_id), "skill_id": str(payload.skill_id), "assigned": False}
