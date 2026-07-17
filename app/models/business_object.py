"""Business Object Registry - AgentX Runtime v2 (Phase 3, flagged).

Describes enterprise business entities (Employee, Leave Request,
Purchase Order, ...) so the runtime can reason in terms of business
meaning rather than raw UI controls. Same versioned-metadata pattern as
UIMetadataEntry (app.models.ui_metadata) - deliberately reused rather
than inventing a third registry shape.
"""
from __future__ import annotations

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CodeMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class BusinessObjectDefinition(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One versioned Business Object definition, e.g. code='leave_request'.

    `fields`, `relationships`, `validation`, and `business_meaning` are
    stored as a single JSONB payload (schema-agnostic at this layer,
    validated by app.schemas.business_object.BusinessObjectSchema) so
    adding a new descriptive facet never requires a migration.
    """

    __tablename__ = "business_object_definitions"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_business_object_code_version"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # {"fields": [...], "relationships": [...], "validation": [...], "businessMeaning": "..."}
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<BusinessObjectDefinition code={self.code} v{self.version}>"
