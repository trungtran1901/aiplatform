from __future__ import annotations

from sqlalchemy import select

from app.models.ui_metadata import UIMetadataEntry, UIMetadataKind
from app.repositories.base import BaseRepository


class UIMetadataRepository(BaseRepository[UIMetadataEntry]):
    model = UIMetadataEntry

    async def get_latest(self, code: str, *, kind: UIMetadataKind | None = None) -> UIMetadataEntry | None:
        """Returns the highest-version, enabled, non-deleted entry for a
        code (optionally scoped to a kind, since codes are only unique
        per (code, kind, version)) - the "give me the current metadata"
        read path the Context Engine uses."""
        stmt = (
            select(UIMetadataEntry)
            .where(
                UIMetadataEntry.code == code,
                UIMetadataEntry.deleted_at.is_(None),
                UIMetadataEntry.enabled.is_(True),
            )
            .order_by(UIMetadataEntry.version.desc())
            .limit(1)
        )
        if kind is not None:
            stmt = stmt.where(UIMetadataEntry.kind == kind)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_versions(self, code: str, kind: UIMetadataKind) -> list[UIMetadataEntry]:
        stmt = (
            select(UIMetadataEntry)
            .where(
                UIMetadataEntry.code == code,
                UIMetadataEntry.kind == kind,
                UIMetadataEntry.deleted_at.is_(None),
            )
            .order_by(UIMetadataEntry.version.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def next_version(self, code: str, kind: UIMetadataKind) -> int:
        versions = await self.list_versions(code, kind)
        return versions[0].version + 1 if versions else 1

    async def list_children(self, parent_code: str) -> list[UIMetadataEntry]:
        """All non-deleted entries whose parent_code matches - e.g. every
        Form under a Page code."""
        stmt = select(UIMetadataEntry).where(
            UIMetadataEntry.parent_code == parent_code,
            UIMetadataEntry.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
