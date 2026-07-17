"""Business Object Registry API - AgentX v2 Phase 3, flagged behind
FEATURE_BUSINESS_OBJECT_REGISTRY. Same create/update-versions/get-latest
pattern as ui_metadata.py (app.api.v1.ui_metadata) - deliberately
identical shape so both registries are predictable to a caller who has
already learned one of them."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.repositories.business_object_repository import BusinessObjectRepository
from app.schemas.business_object import BusinessObjectCreate, BusinessObjectRead, BusinessObjectUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/business-objects", tags=["Business Object Registry (v2, flagged)"])


def _require_enabled() -> None:
    if not get_settings().FEATURE_BUSINESS_OBJECT_REGISTRY:
        raise NotFoundError("Business Object Registry is not enabled on this deployment")


@router.get("", response_model=PaginatedResponse[BusinessObjectRead])
async def list_business_objects(pagination: PaginationParams = Depends(), db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = BusinessObjectRepository(db)
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit)
    return PaginatedResponse[BusinessObjectRead](
        items=[BusinessObjectRead.model_validate(i) for i in items],
        total=total, page=pagination.page, page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=BusinessObjectRead, status_code=status.HTTP_201_CREATED)
async def create_business_object(payload: BusinessObjectCreate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = BusinessObjectRepository(db)
    next_version = await repo.next_version(payload.code)
    data = payload.model_dump()
    data["version"] = next_version
    data["payload"] = data.pop("payload")
    obj = await repo.create(**data)
    return BusinessObjectRead.model_validate(obj)


@router.get("/{object_id}", response_model=BusinessObjectRead)
async def get_business_object(object_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = BusinessObjectRepository(db)
    obj = await repo.get_or_404(object_id)
    return BusinessObjectRead.model_validate(obj)


@router.get("/by-code/{code}/latest", response_model=BusinessObjectRead)
async def get_latest_business_object(code: str, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = BusinessObjectRepository(db)
    obj = await repo.get_latest(code)
    if obj is None:
        raise NotFoundError(f"No enabled business object found for code='{code}'")
    return BusinessObjectRead.model_validate(obj)


@router.put("/{object_id}", response_model=BusinessObjectRead)
async def update_business_object(object_id: UUID, payload: BusinessObjectUpdate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = BusinessObjectRepository(db)
    existing = await repo.get_or_404(object_id)
    next_version = await repo.next_version(existing.code)

    merged = BusinessObjectRead.model_validate(existing).model_dump()
    for key, value in payload.model_dump(exclude_unset=True).items():
        merged[key] = value
    merged["version"] = next_version
    for k in ("id", "created_at", "updated_at"):
        merged.pop(k, None)

    obj = await repo.create(**merged)
    return BusinessObjectRead.model_validate(obj)


@router.delete("/{object_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business_object(object_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = BusinessObjectRepository(db)
    obj = await repo.get_or_404(object_id)
    await repo.soft_delete(obj)
