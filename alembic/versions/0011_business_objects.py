"""add business_object_definitions table (AgentX Runtime v2 - Phase 3)

Revision ID: 0011_business_objects
Revises: 0010_ui_skill_type
Create Date: 2026-07-08

Purely additive: one new table, versioned exactly like
ui_metadata_entries / prompts ((code, version) unique).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_business_objects"
down_revision = "0010_ui_skill_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_object_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", "version", name="uq_business_object_code_version"),
    )
    op.create_index("ix_business_object_definitions_code", "business_object_definitions", ["code"])
    op.create_index("ix_business_object_definitions_deleted_at", "business_object_definitions", ["deleted_at"])


def downgrade() -> None:
    op.drop_table("business_object_definitions")
