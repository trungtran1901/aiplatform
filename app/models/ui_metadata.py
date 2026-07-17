"""UI Metadata Registry - Phase 1 of AgentX Runtime v2.

Stores semantic metadata describing enterprise UI applications (pages,
forms, business objects, fields, validation, lookups) so a future
Context Engine / UI Skill layer can reason about "what's on screen"
without ever touching the DOM. This module stores METADATA only -
runtime UI state (current page, selected record, etc.) is NOT persisted
here; it travels per-request via ChatRequest's new optional fields (see
app/schemas/chat.py) and is assembled by the (flagged) Context Engine.

Follows the exact same table/model pattern as app.models.skill.Skill:
CodeMixin for a human-facing unique code, SoftDeleteMixin (metadata,
never hard-deleted, same rationale as every other metadata table),
JSONB for the actual schema payload (kept schema-agnostic here - shape
validation happens at the Pydantic layer, same division of
responsibility as Skill.config / KnowledgeSkillConfig).
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CodeMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UIMetadataKind(str, Enum):
    """What this metadata entry describes. Mirrors the spec's list
    (Applications, Pages, Forms, Dialogs, Grids, Business Objects,
    Fields, Validation Rules, Lookups, Business Rules, Components,
    Permissions, Events) collapsed into a flat, extensible enum rather
    than one table per kind - keeps this additive to the schema (one
    new enum value in a future migration) instead of a new table every
    time the UI team invents a new artifact type.
    """

    application = "APPLICATION"
    page = "PAGE"
    form = "FORM"
    dialog = "DIALOG"
    grid = "GRID"
    business_object = "BUSINESS_OBJECT"
    field = "FIELD"
    validation_rule = "VALIDATION_RULE"
    lookup = "LOOKUP"
    business_rule = "BUSINESS_RULE"
    component = "COMPONENT"
    permission = "PERMISSION"
    event = "EVENT"


class UIMetadataEntry(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One versioned metadata artifact.

    Versioning: (code, kind, version) is unique. Callers fetch either an
    exact version or "latest" (highest version, see repository), the
    same pattern app.models.prompt.Prompt already uses for
    (code, version) - deliberately reused rather than inventing a
    second versioning scheme.
    """

    __tablename__ = "ui_metadata_entries"
    __table_args__ = (
        UniqueConstraint("code", "kind", "version", name="uq_ui_metadata_code_kind_version"),
    )

    kind: Mapped[UIMetadataKind] = mapped_column(
        SAEnum(UIMetadataKind, name="ui_metadata_kind", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Optional hierarchy: a Page/Form/Grid/Field typically belongs to an
    # Application; nullable + self-referencing-by-code (not FK to keep
    # cross-kind parenting simple) so a Field can point at its Form,
    # a Form at its Page, a Page at its Application, etc.
    parent_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # The actual metadata payload (schema-agnostic here; each `kind` has
    # its own expected shape, validated at the Pydantic schema layer
    # exactly like Skill.config / KnowledgeSkillConfig - this model has
    # zero opinion about its contents).
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<UIMetadataEntry code={self.code} kind={self.kind} v{self.version}>"
