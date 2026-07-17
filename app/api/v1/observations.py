"""Read API for the Observation Engine - AgentX v2 Phase 6, flagged.
Write path is internal only (ObservationEngineService.record, called
from execution/knowledge/UI-action code paths) - there is no public
POST endpoint, since observations are meant to be a faithful runtime
record, not user-editable data."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.repositories.observation_repository import ObservationRepository
from app.schemas.common import PaginatedResponse
from app.schemas.observation import ObservationRead

router = APIRouter(prefix="/observations", tags=["Observation Engine (v2, flagged)"])


def _require_enabled() -> None:
    if not get_settings().FEATURE_OBSERVATION_ENGINE:
        raise NotFoundError("Observation Engine is not enabled on this deployment")


@router.get("", response_model=PaginatedResponse[ObservationRead])
async def list_observations(
    run_id: UUID | None = Query(default=None),
    workflow_run_id: UUID | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    repo = ObservationRepository(db)
    items, total = await repo.list(
        offset=pagination.offset, limit=pagination.limit, run_id=run_id, workflow_run_id=workflow_run_id
    )
    return PaginatedResponse[ObservationRead](
        items=[ObservationRead.model_validate(i) for i in items],
        total=total, page=pagination.page, page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )
