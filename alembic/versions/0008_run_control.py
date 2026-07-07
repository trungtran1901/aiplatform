"""add cancelled run_status + run_cancelled event_type (stop/cancel support)

Revision ID: 0008_run_control
Revises: 0007_knowledge_skills
Create Date: 2026-07-08

Adds the two enum values needed to support POST /api/v1/runs/{id}/cancel
(stop an in-flight agent run mid-stream, analogous to a "stop
generating" button): RunStatus.cancelled and EventType.run_cancelled.

Postgres requires ALTER TYPE ... ADD VALUE to run outside an explicit
transaction block in older server versions - same autocommit_block
pattern already used in 0003_agentic_memory.py.
"""
from __future__ import annotations

from alembic import op

revision = "0008_run_control"
down_revision = "0007_knowledge_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'cancelled'")
        op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'run_cancelled'")


def downgrade() -> None:
    # Postgres does not support removing a value from an enum type
    # directly - same limitation documented in 0003_agentic_memory.py.
    # Left in place (harmless if unused) rather than rebuilding the
    # entire enum type and every column that depends on it.
    pass