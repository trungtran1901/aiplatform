"""add agno_team_sessions table for AgnoTeam conversation history storage

Revision ID: 0006_agno_team_sessions
Revises: 0005_agno_agent_sessions
Create Date: 2026-07-02

In the platform's architecture, requests are dispatched to an AgnoTeam
(coordinator) which then delegates to member AgnoAgents. Conversation
history for the team-level coordinator is tracked in the Team's own
`Memory.runs` dict (keyed by session_id). Without a storage backend,
this dict is discarded after every request, making `add_history_to_messages=True`
a no-op on the Team coordinator.

This migration creates `agno_team_sessions` in the `public` schema,
mirroring exactly what Agno's PostgresStorage.get_table_v1() defines
for mode="team":

  session_id       TEXT PRIMARY KEY  - Agno session_id (the chat session UUID)
  user_id          TEXT              - user identifier (optional)
  memory           JSONB             - Team Memory obj incl. runs / messages
  session_data     JSONB             - extra session-level metadata
  extra_data       JSONB             - catch-all for future Agno fields
  created_at       BIGINT            - unix epoch (server default on INSERT)
  updated_at       BIGINT            - unix epoch (updated on each UPSERT)
  team_id          TEXT              - platform team UUID as string (mode=team)
  team_session_id  TEXT              - populated when part of a parent Team
  team_data        JSONB             - team-level metadata (mode=team)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_agno_team_sessions"
down_revision = "0005_agno_agent_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agno_team_sessions",
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
            comment="Serialized Memory: runs[], summaries — source of truth for Team history injection",
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
        # ---- mode="team" specific columns ----
        sa.Column(
            "team_id",
            sa.Text(),
            nullable=True,
            comment="Platform team UUID as string",
        ),
        sa.Column(
            "team_session_id",
            sa.Text(),
            nullable=True,
            comment="Set by Agno when this team session is a member of a parent Team",
        ),
        sa.Column(
            "team_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Team-level metadata persisted by Agno",
        ),
        sa.PrimaryKeyConstraint("session_id", name="agno_team_sessions_pkey"),
    )
    op.create_index(
        "ix_agno_team_sessions_user_id",
        "agno_team_sessions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_agno_team_sessions_team_id",
        "agno_team_sessions",
        ["team_id"],
        unique=False,
    )
    op.create_index(
        "ix_agno_team_sessions_team_session_id",
        "agno_team_sessions",
        ["team_session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agno_team_sessions_team_session_id", table_name="agno_team_sessions")
    op.drop_index("ix_agno_team_sessions_team_id", table_name="agno_team_sessions")
    op.drop_index("ix_agno_team_sessions_user_id", table_name="agno_team_sessions")
    op.drop_table("agno_team_sessions")
