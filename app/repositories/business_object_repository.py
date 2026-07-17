from __future__ import annotations

from sqlalchemy import select

from app.models.business_object import BusinessObjectDefinition
from app.repositories.base import BaseRepository


class BusinessObjectRepository(BaseRepository[BusinessObjectDefinition]):
    model = BusinessObjectDefinition

    async def get_latest(self, code: str) -> BusinessObjectDefinition | None:
        stmt = (
            select(BusinessObjectDefinition)
            .where(
                BusinessObjectDefinition.code == code,
                BusinessObjectDefinition.deleted_at.is_(None),
                BusinessObjectDefinition.enabled.is_(True),
            )
            .order_by(BusinessObjectDefinition.version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def next_version(self, code: str) -> int:
        stmt = (
            select(BusinessObjectDefinition.version)
            .where(BusinessObjectDefinition.code == code, BusinessObjectDefinition.deleted_at.is_(None))
            .order_by(BusinessObjectDefinition.version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        current = result.scalar_one_or_none()
        return (current + 1) if current else 1
