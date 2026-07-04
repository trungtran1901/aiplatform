"""Declarative base class plus shared mixins used by all ORM models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
        nullable=False,
    )


class SoftDeleteMixin:
    """Soft delete support.

    Metadata entities (AgentOS, Team, Agent, Prompt, Skill, ModelRegistry)
    are never hard-deleted because Runs/Events/Sessions hold foreign keys
    into them for audit/observability purposes. DELETE API calls set
    deleted_at instead of removing the row.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class CodeMixin:
    """Human-readable, API-facing unique identifier (e.g. 'enterprise', 'sales')."""

    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
