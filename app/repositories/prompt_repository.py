from __future__ import annotations

from sqlalchemy import select

from app.models.prompt import Prompt, PromptStatus
from app.repositories.base import BaseRepository


class PromptRepository(BaseRepository[Prompt]):
    model = Prompt

    async def get_active_by_code(self, code: str) -> Prompt | None:
        """Returns the highest-version ACTIVE prompt for a given code."""
        stmt = (
            select(Prompt)
            .where(
                Prompt.code == code,
                Prompt.status == PromptStatus.active,
                Prompt.deleted_at.is_(None),
            )
            .order_by(Prompt.version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_versions(self, code: str) -> list[Prompt]:
        stmt = (
            select(Prompt)
            .where(Prompt.code == code, Prompt.deleted_at.is_(None))
            .order_by(Prompt.version.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def next_version(self, code: str) -> int:
        versions = await self.list_versions(code)
        if not versions:
            return 1
        return versions[0].version + 1
