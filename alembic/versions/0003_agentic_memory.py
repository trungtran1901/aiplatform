"""add source_memory_id to agent_memories + memory_update event types

Revision ID: 0003_agentic_memory
Revises: 0002_model_registry_base_url
Create Date: 2026-06-21

Adds support for Agno's agentic memory (agno.memory.v2.Memory +
MemoryManager): an LLM that self-extracts facts/preferences after each
chat turn, ChatGPT-memory style (see app/agno_runtime/memory_db.py,
app/agno_runtime/engine.py). Agno tracks each extracted memory by its
own native `memory_id` - source_memory_id lets the platform's
agent_memories table store that alongside the durable record, so
re-syncing/upserting after later runs updates the same row instead of
duplicating it. NULL for memories created directly via a future
platform API rather than by Agno.

Also extends the event_type enum with memory_update_started /
memory_update_completed, emitted by Agno around its (awaited,
synchronous-from-the-run's-perspective) memory extraction step.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_agentic_memory"
down_revision = "0002_model_registry_base_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_memories", sa.Column("source_memory_id", sa.String(255), nullable=True))
    op.create_index(
        "ix_agent_memories_source_memory_id", "agent_memories", ["source_memory_id"]
    )
    op.create_unique_constraint(
        "uq_agent_memory_source",
        "agent_memories",
        ["agent_id", "user_id", "source_memory_id"],
    )

    # Postgres requires ALTER TYPE ... ADD VALUE to run outside an
    # explicit transaction block in older server versions (pre-12 could
    # not do it at all inside one; modern Postgres permits it but
    # Alembic still recommends autocommit for safety across versions).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'memory_update_started'")
        op.execute("ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'memory_update_completed'")


def downgrade() -> None:
    # Postgres does not support removing a value from an enum type
    # directly. Downgrading this migration only reverts the
    # agent_memories column/constraint changes; the two added event_type
    # values are left in place (harmless if unused) rather than rebuilding
    # the entire enum type and every column that depends on it.
    op.drop_constraint("uq_agent_memory_source", "agent_memories", type_="unique")
    op.drop_index("ix_agent_memories_source_memory_id", table_name="agent_memories")
    op.drop_column("agent_memories", "source_memory_id")