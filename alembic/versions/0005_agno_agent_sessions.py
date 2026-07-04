"""add agno_agent_sessions table for Agno conversation history storage

Revision ID: 0005_agno_agent_sessions
Revises: 0004_workflows
Create Date: 2026-07-02

Agno's Agent requires a `storage` backend to persist conversation history
(Memory.runs) across requests. Without it, `add_history_to_messages=True`
has no effect because `Memory.runs` is an in-memory dict that is discarded
at the end of every request.

This migration creates the `agno_agent_sessions` table in the `public`
schema (matching all other platform tables - no separate `ai` schema).

The table schema mirrors EXACTLY what Agno's PostgresStorage.get_table_v1()
defines for mode="agent" (see agno/storage/postgres.py), so the Alembic
table and the Agno ORM table always describe the same columns:

  session_id       TEXT PRIMARY KEY  - Agno session_id (the chat session UUID)
  user_id          TEXT              - user identifier (optional)
  memory           JSONB             - Memory obj incl. runs / message history
  session_data     JSONB             - extra session-level metadata
  extra_data       JSONB             - catch-all for future Agno fields
  created_at       BIGINT            - unix epoch (set by server default)
  updated_at       BIGINT            - unix epoch (updated on write)
  agent_id         TEXT              - platform agent UUID as string (mode=agent)
  team_session_id  TEXT              - populated when this agent is part of a Team
  agent_data       JSONB             - agent-level metadata (mode=agent)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_agno_agent_sessions"
down_revision = "0004_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agno_agent_sessions",
        # ---- common columns (same for all modes in PostgresStorage) ----
        sa.Column(
            "session_id",
            sa.Text(),
            nullable=False,
            comment="Agno session_id — matches chat_sessions.id (UUID as string)",
        ),
        sa.Column("user_id", sa.Text(), nullable=True, comment="User identifier (optional)"),
        sa.Column(
            "memory",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Serialized Memory: runs[], summaries, user-memories — the source of truth for history injection",
        ),
        sa.Column(
            "session_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Extra session-level metadata persisted by Agno",
        ),
        sa.Column(
            "extra_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Catch-all for future Agno fields",
        ),
        sa.Column(
            "created_at",
            sa.BigInteger(),
            nullable=True,
            server_default=sa.text("(extract(epoch from now()))::bigint"),
            comment="Unix timestamp (seconds) — set automatically on INSERT",
        ),
        sa.Column(
            "updated_at",
            sa.BigInteger(),
            nullable=True,
            comment="Unix timestamp (seconds) — updated on each UPSERT by Agno",
        ),
        # ---- mode="agent" specific columns ----
        sa.Column(
            "agent_id",
            sa.Text(),
            nullable=True,
            comment="Platform agent UUID as string",
        ),
        sa.Column(
            "team_session_id",
            sa.Text(),
            nullable=True,
            comment="Set by Agno when this agent session is a member of a Team session",
        ),
        sa.Column(
            "agent_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Agent-level metadata persisted by Agno",
        ),
        sa.PrimaryKeyConstraint("session_id", name="agno_agent_sessions_pkey"),
    )
    op.create_index(
        "ix_agno_agent_sessions_user_id",
        "agno_agent_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_agno_agent_sessions_agent_id",
        "agno_agent_sessions",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agno_agent_sessions_team_session_id",
        "agno_agent_sessions",
        ["team_session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agno_agent_sessions_team_session_id", table_name="agno_agent_sessions")
    op.drop_index("ix_agno_agent_sessions_agent_id", table_name="agno_agent_sessions")
    op.drop_index("ix_agno_agent_sessions_user_id", table_name="agno_agent_sessions")
    op.drop_table("agno_agent_sessions")
