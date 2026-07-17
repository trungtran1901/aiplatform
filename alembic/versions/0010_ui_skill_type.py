"""add UI value to skill_type enum (AgentX Runtime v2 - Phase 4)

Revision ID: 0010_ui_skill_type
Revises: 0009_ui_metadata_registry
Create Date: 2026-07-08

Purely additive: one new enum value on the existing skill_type enum,
same ALTER TYPE ... ADD VALUE pattern as 0003/0008. No existing Skill
row, column, or behavior is touched - a deployment that never creates a
skill_type=UI Skill sees zero difference.
"""
from __future__ import annotations

from alembic import op

revision = "0010_ui_skill_type"
down_revision = "0009_ui_metadata_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE skill_type ADD VALUE IF NOT EXISTS 'UI'")


def downgrade() -> None:
    # Postgres cannot drop a single enum value - same limitation
    # documented in every prior ADD VALUE migration in this repo.
    pass
