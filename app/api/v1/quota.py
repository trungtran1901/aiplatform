"""Quota Management API - flagged behind FEATURE_QUOTA_MANAGEMENT.

Management endpoints (create/list/update/delete policies) follow the
same shape as every other metadata registry in this codebase (see
app/api/v1/ui_metadata.py). GET /quota/usage exposes the durable
Postgres audit trail for a given user - not the Redis counters, which
are enforcement-only and reset per period; usage history should be
queried here, not by inspecting Redis directly.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.repositories.quota_repository import QuotaPolicyRepository
from app.schemas.common import PaginatedResponse
from app.schemas.quota import QuotaPolicyCreate, QuotaPolicyRead, QuotaPolicyUpdate, QuotaUsageRead
from app.services.quota_service import QuotaService

router = APIRouter(prefix="/quota", tags=["Quota Management (v2, flagged)"])


def _require_enabled() -> None:
    if not get_settings().FEATURE_QUOTA_MANAGEMENT:
        raise NotFoundError("Quota Management is not enabled on this deployment")


@router.get("/policies", response_model=PaginatedResponse[QuotaPolicyRead])
async def list_quota_policies(
    scope_type: str | None = Query(default=None),
    scope_value: str | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    repo = QuotaPolicyRepository(db)
    filters = {}
    if scope_type:
        filters["scope_type"] = scope_type
    if scope_value is not None:
        filters["scope_value"] = scope_value
    items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, **filters)
    return PaginatedResponse[QuotaPolicyRead](
        items=[QuotaPolicyRead.model_validate(i) for i in items],
        total=total, page=pagination.page, page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("/policies", response_model=QuotaPolicyRead, status_code=status.HTTP_201_CREATED)
async def create_quota_policy(payload: QuotaPolicyCreate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = QuotaPolicyRepository(db)
    obj = await repo.create(**payload.model_dump())
    return QuotaPolicyRead.model_validate(obj)


@router.get("/policies/{policy_id}", response_model=QuotaPolicyRead)
async def get_quota_policy(policy_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = QuotaPolicyRepository(db)
    obj = await repo.get_or_404(policy_id)
    return QuotaPolicyRead.model_validate(obj)


@router.put("/policies/{policy_id}", response_model=QuotaPolicyRead)
async def update_quota_policy(policy_id: UUID, payload: QuotaPolicyUpdate, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = QuotaPolicyRepository(db)
    obj = await repo.get_or_404(policy_id)
    obj = await repo.update(obj, **payload.model_dump(exclude_unset=True))
    return QuotaPolicyRead.model_validate(obj)


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quota_policy(policy_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_enabled()
    repo = QuotaPolicyRepository(db)
    obj = await repo.get_or_404(policy_id)
    await repo.soft_delete(obj)


@router.get("/usage", response_model=QuotaUsageRead)
async def get_quota_usage(
    user_id: str = Query(...),
    since_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    service = QuotaService(db)
    snapshot = await service.get_usage_snapshot(user_id=user_id, since_days=since_days)
    return QuotaUsageRead(user_id=user_id, since_days=since_days, **snapshot)