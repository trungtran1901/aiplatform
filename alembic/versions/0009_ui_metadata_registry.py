"""add ui_metadata_entries table (AgentX Runtime v2 - Phase 1)

Revision ID: 0009_ui_metadata_registry
Revises: 0008_run_control
Create Date: 2026-07-08

Purely additive: one new table, one new enum type. No existing table,
column, or enum is touched - safe for zero-downtime deployment and a
no-op for any deployment that keeps FEATURE_UI_METADATA_REGISTRY=false.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_ui_metadata_registry"
down_revision = "0008_run_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ui_metadata_kind = postgresql.ENUM(
        "APPLICATION", "PAGE", "FORM", "DIALOG", "GRID", "BUSINESS_OBJECT",
        "FIELD", "VALIDATION_RULE", "LOOKUP", "BUSINESS_RULE", "COMPONENT",
        "PERMISSION", "EVENT",
        name="ui_metadata_kind", create_type=False,
    )
    bind = op.get_bind()
    ui_metadata_kind.create(bind, checkfirst=True)

    op.create_table(
        "ui_metadata_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("kind", ui_metadata_kind, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("parent_code", sa.String(128), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", "kind", "version", name="uq_ui_metadata_code_kind_version"),
    )
    op.create_index("ix_ui_metadata_entries_code", "ui_metadata_entries", ["code"])
    op.create_index("ix_ui_metadata_entries_kind", "ui_metadata_entries", ["kind"])
    op.create_index("ix_ui_metadata_entries_parent_code", "ui_metadata_entries", ["parent_code"])
    op.create_index("ix_ui_metadata_entries_deleted_at", "ui_metadata_entries", ["deleted_at"])


def downgrade() -> None:
    op.drop_table("ui_metadata_entries")
    bind = op.get_bind()
    postgresql.ENUM(name="ui_metadata_kind").drop(bind, checkfirst=True)
