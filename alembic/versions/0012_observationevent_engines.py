"""add runtime_observations + runtime_events tables (AgentX v2 Phase 6+7)

Revision ID: 0012_observation_and_event_engines
Revises: 0011_business_objects
Create Date: 2026-07-08

Purely additive: two new, independent append-only tables. Neither is
referenced by any existing table via FK (deliberately loosely-coupled -
see model docstrings), so this migration cannot fail against any
existing data.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_obs_events"
down_revision = "0011_business_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    observation_type = postgresql.ENUM(
        "KNOWLEDGE_RETRIEVAL", "SKILL_OUTPUT", "BUSINESS_RESPONSE", "UI_RESULT", "WARNING", "ERROR",
        name="observation_type", create_type=False,
    )
    bind = op.get_bind()
    observation_type.create(bind, checkfirst=True)

    op.create_table(
        "runtime_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observation_type", observation_type, nullable=False),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("execution_time_ms", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_runtime_observations_run_id", "runtime_observations", ["run_id"])
    op.create_index("ix_runtime_observations_workflow_run_id", "runtime_observations", ["workflow_run_id"])
    op.create_index("ix_runtime_observations_agent_id", "runtime_observations", ["agent_id"])
    op.create_index("ix_runtime_observations_observation_type", "runtime_observations", ["observation_type"])

    op.create_table(
        "runtime_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("event_name", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_runtime_events_entity_type", "runtime_events", ["entity_type"])
    op.create_index("ix_runtime_events_entity_id", "runtime_events", ["entity_id"])
    op.create_index("ix_runtime_events_event_name", "runtime_events", ["event_name"])
    op.create_index("ix_runtime_events_correlation_id", "runtime_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_table("runtime_events")
    op.drop_table("runtime_observations")
    bind = op.get_bind()
    postgresql.ENUM(name="observation_type").drop(bind, checkfirst=True)
