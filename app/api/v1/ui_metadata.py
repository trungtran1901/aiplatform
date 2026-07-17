"""UI Metadata Registry API.

Gated by settings.FEATURE_UI_METADATA_REGISTRY - the router is still
registered (so /docs always shows it for discoverability) but every
handler 404s immediately when the flag is off, so no behavior changes
for anyone not opting in, and there is exactly one place to see whether
the feature is live.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.ui_metadata import UIMetadataKind
from app.repositories.ui_metadata_repository import UIMetadataRepository
from app.schemas.common import PaginatedResponse
from app.schemas.ui_metadata import UIMetadataCreate, UIMetadataRead, UIMetadataUpdate

router = APIRouter(prefix="/ui-metadata", tags=["UI Metadata Registry (v2, flagged)"])


def _require_feature_enabled() -> None:
    if not get_settings().FEATURE_UI_METADATA_REGISTRY:
        raise NotFoundError("UI Metadata Registry is not enabled on this deployment")


@router.get("", response_model=PaginatedResponse[UIMetadataRead])
async def list_ui_metadata(
    kind: UIMetadataKind | None = Query(default=None),
    parent_code: str | None = Query(default=None),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    _require_feature_enabled()
    repo = UIMetadataRepository(db)
    if parent_code is not None:
        items = await repo.list_children(parent_code)
        total = len(items)
        items = items[pagination.offset : pagination.offset + pagination.limit]
    else:
        items, total = await repo.list(offset=pagination.offset, limit=pagination.limit, kind=kind)
    return PaginatedResponse[UIMetadataRead](
        items=[UIMetadataRead.model_validate(i) for i in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        has_next=pagination.offset + pagination.limit < total,
    )


@router.post("", response_model=UIMetadataRead, status_code=status.HTTP_201_CREATED)
async def create_ui_metadata(payload: UIMetadataCreate, db: AsyncSession = Depends(get_db)):
    _require_feature_enabled()
    repo = UIMetadataRepository(db)
    next_version = await repo.next_version(payload.code, payload.kind)
    data = payload.model_dump()
    data["version"] = next_version
    obj = await repo.create(**data)
    return UIMetadataRead.model_validate(obj)


@router.get("/{entry_id}", response_model=UIMetadataRead)
async def get_ui_metadata(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_feature_enabled()
    repo = UIMetadataRepository(db)
    obj = await repo.get_or_404(entry_id)
    return UIMetadataRead.model_validate(obj)


@router.get("/by-code/{code}/latest", response_model=UIMetadataRead)
async def get_latest_ui_metadata(
    code: str, kind: UIMetadataKind | None = Query(default=None), db: AsyncSession = Depends(get_db)
):
    """The read path the Context Engine actually uses: "give me
    whatever the current version of this artifact is."""
    _require_feature_enabled()
    repo = UIMetadataRepository(db)
    obj = await repo.get_latest(code, kind=kind)
    if obj is None:
        raise NotFoundError(f"No enabled UI metadata found for code='{code}'")
    return UIMetadataRead.model_validate(obj)


@router.put("/{entry_id}", response_model=UIMetadataRead)
async def update_ui_metadata(entry_id: UUID, payload: UIMetadataUpdate, db: AsyncSession = Depends(get_db)):
    """Creates a NEW version rather than mutating in place - same
    immutability-with-versioning approach as Prompt, so the Context
    Engine resolving "latest" never sees history silently rewritten
    under it."""
    _require_feature_enabled()
    repo = UIMetadataRepository(db)
    existing = await repo.get_or_404(entry_id)

    next_version = await repo.next_version(existing.code, existing.kind)
    merged = UIMetadataRead.model_validate(existing).model_dump()
    for key, value in payload.model_dump(exclude_unset=True).items():
        merged[key] = value
    merged["version"] = next_version
    merged.pop("id", None)
    merged.pop("created_at", None)
    merged.pop("updated_at", None)

    obj = await repo.create(**merged)
    return UIMetadataRead.model_validate(obj)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ui_metadata(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    _require_feature_enabled()
    repo = UIMetadataRepository(db)
    obj = await repo.get_or_404(entry_id)
    await repo.soft_delete(obj)
