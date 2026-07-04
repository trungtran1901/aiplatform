from __future__ import annotations

from sqlalchemy import select

from app.models.model_registry import ModelRegistry
from app.repositories.base import BaseRepository


class ModelRegistryRepository(BaseRepository[ModelRegistry]):
    model = ModelRegistry

    async def get_by_provider_model(self, provider: str, model: str) -> ModelRegistry | None:
        stmt = select(ModelRegistry).where(
            ModelRegistry.provider == provider,
            ModelRegistry.model == model,
            ModelRegistry.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
