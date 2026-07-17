"""add execution_plan_runs + execution_plan_step_runs (AgentX v2 Phase 9)

Revision ID: 0013_execution_engine
Revises: 0012_observation_and_event_engines
Create Date: 2026-07-08

Purely additive audit-trail tables for the (flagged) Execution Engine,
mirroring workflow_runs/workflow_run_steps' shape but for ad-hoc,
non-persisted ExecutionPlans.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_execution_engine"
down_revision = "0012_obs_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    plan_run_status = postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED", name="execution_plan_run_status", create_type=False
    )
    step_status = postgresql.ENUM(
        "PENDING", "RUNNING", "RETRYING", "COMPLETED", "FAILED", name="execution_step_status", create_type=False
    )
    bind = op.get_bind()
    plan_run_status.create(bind, checkfirst=True)
    step_status.create(bind, checkfirst=True)

    op.create_table(
        "execution_plan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input", sa.Text, nullable=False),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("status", plan_run_status, nullable=False),
        sa.Column("result", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_execution_plan_runs_session_id", "execution_plan_runs", ["session_id"])
    op.create_index("ix_execution_plan_runs_status", "execution_plan_runs", ["status"])

    op.create_table(
        "execution_plan_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_plan_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_code", sa.String(255), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input", sa.Text, nullable=True),
        sa.Column("output", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_execution_plan_step_runs_plan_run_id", "execution_plan_step_runs", ["plan_run_id"])
    op.create_index("ix_execution_plan_step_runs_status", "execution_plan_step_runs", ["status"])


def downgrade() -> None:
    op.drop_table("execution_plan_step_runs")
    op.drop_table("execution_plan_runs")
    bind = op.get_bind()
    postgresql.ENUM(name="execution_step_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="execution_plan_run_status").drop(bind, checkfirst=True)
