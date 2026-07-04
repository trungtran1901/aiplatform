from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.exceptions import ConflictError
from app.repositories.model_repository import ModelRegistryRepository
from app.schemas.common import PaginatedResponse
from app.schemas.model_registry import ModelRegistryCreate, ModelRegistryRead, ModelRegistryUpdate

router = APIRouter(prefix="/models", tags=["Model Registry"])


@router.get("", response_model=PaginatedResponse[ModelRegistryRead])
async def list_models(pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)):
    repo = ModelRegistryRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit)
    return PaginatedResponse[ModelRegistryRead](
        items=[ModelRegistryRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=ModelRegistryRead, status_code=status.HTTP_201_CREATED)
async def create_model(payload: ModelRegistryCreate, db: AsyncSession = Depends(get_db)):
    repo = ModelRegistryRepository(db)
    existing = await repo.get_by_provider_model(payload.provider, payload.model)
    if existing is not None:
        raise ConflictError(f"Model '{payload.provider}/{payload.model}' already registered")
    obj = await repo.create(**payload.model_dump())
    return ModelRegistryRead.model_validate(obj)


@router.get("/{model_id}", response_model=ModelRegistryRead)
async def get_model(model_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = ModelRegistryRepository(db)
    obj = await repo.get_or_404(model_id)
    return ModelRegistryRead.model_validate(obj)


@router.put("/{model_id}", response_model=ModelRegistryRead)
async def update_model(model_id: UUID, payload: ModelRegistryUpdate, db: AsyncSession = Depends(get_db)):
    repo = ModelRegistryRepository(db)
    obj = await repo.get_or_404(model_id)
    obj = await repo.update(obj, **payload.model_dump(exclude_unset=True))
    return ModelRegistryRead.model_validate(obj)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = ModelRegistryRepository(db)
    obj = await repo.get_or_404(model_id)
    await repo.soft_delete(obj)
