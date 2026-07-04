from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.repositories.prompt_repository import PromptRepository
from app.schemas.common import PaginatedResponse
from app.schemas.prompt import PromptCreate, PromptRead, PromptUpdate

router = APIRouter(prefix="/prompts", tags=["Prompts"])


@router.get("", response_model=PaginatedResponse[PromptRead])
async def list_prompts(
    code: str | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    repo = PromptRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, code=code)
    return PaginatedResponse[PromptRead](
        items=[PromptRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=PromptRead, status_code=status.HTTP_201_CREATED)
async def create_prompt(payload: PromptCreate, db: AsyncSession = Depends(get_db)):
    repo = PromptRepository(db)
    # version is auto-assigned per code unless caller explicitly set one
    # beyond the default of 1 - in practice, callers POST without
    # specifying version and the repo computes the next one.
    next_version = await repo.next_version(payload.code)
    data = payload.model_dump()
    data["version"] = next_version
    obj = await repo.create(**data)
    return PromptRead.model_validate(obj)


@router.get("/{prompt_id}", response_model=PromptRead)
async def get_prompt(prompt_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = PromptRepository(db)
    obj = await repo.get_or_404(prompt_id)
    return PromptRead.model_validate(obj)


@router.put("/{prompt_id}", response_model=PromptRead)
async def update_prompt(prompt_id: UUID, payload: PromptUpdate, db: AsyncSession = Depends(get_db)):
    repo = PromptRepository(db)
    obj = await repo.get_or_404(prompt_id)
    obj = await repo.update(obj, **payload.model_dump(exclude_unset=True))
    return PromptRead.model_validate(obj)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(prompt_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = PromptRepository(db)
    obj = await repo.get_or_404(prompt_id)
    await repo.soft_delete(obj)
