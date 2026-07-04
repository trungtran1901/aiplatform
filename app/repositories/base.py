"""Generic repository base providing soft-delete-aware CRUD operations.

All metadata repositories (AgentOS, Team, Agent, Prompt, Skill,
ModelRegistry) inherit from this to avoid duplicating boilerplate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: uuid.UUID, *, include_deleted: bool = False) -> ModelT | None:
        stmt = select(self.model).where(self.model.id == id_)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_404(self, id_: uuid.UUID, *, include_deleted: bool = False) -> ModelT:
        obj = await self.get(id_, include_deleted=include_deleted)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} with id={id_} not found")
        return obj

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        include_deleted: bool = False,
        **filters,
    ) -> tuple[list[ModelT], int]:
        stmt = select(self.model)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        for key, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, key) == value)

        count_stmt = select(self.model).with_only_columns(self.model.id)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            count_stmt = count_stmt.where(self.model.deleted_at.is_(None))
        for key, value in filters.items():
            if value is not None:
                count_stmt = count_stmt.where(getattr(self.model, key) == value)
        total_result = await self.session.execute(count_stmt)
        total = len(total_result.scalars().all())

        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    async def create(self, **kwargs) -> ModelT:
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, obj: ModelT, **kwargs) -> ModelT:
        for key, value in kwargs.items():
            if value is not None:
                setattr(obj, key, value)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def soft_delete(self, obj: ModelT) -> ModelT:
        if not hasattr(obj, "deleted_at"):
            raise NotImplementedError(f"{self.model.__name__} does not support soft delete")
        obj.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return obj

    async def hard_delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
