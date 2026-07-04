"""add workflow module: workflows, workflow_steps, workflow_runs,
workflow_run_steps, workflow_events

Revision ID: 0004_workflows
Revises: 0003_agentic_memory
Create Date: 2026-06-22

Adds the Workflow module per the "AgentOS -> Workflows" extension:
sequential-only AI workflow orchestration over existing Agent/Team
execution (no branching/loops/parallel/approval steps - those remain
out of scope for this runtime).

Table creation order respects FK dependencies:
  workflows (-> agent_os, teams)
  workflow_steps (-> workflows, agents, teams)
  workflow_runs (-> workflows, chat_sessions)
  workflow_run_steps (-> workflow_runs, workflow_steps)
  workflow_events (-> workflow_runs)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_workflows"
down_revision = "0003_agentic_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    workflow_step_type = postgresql.ENUM("AGENT", "TEAM", name="workflow_step_type", create_type=False)
    workflow_run_status = postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED", name="workflow_run_status", create_type=False
    )
    workflow_step_status = postgresql.ENUM(
        "PENDING", "RUNNING", "COMPLETED", "FAILED", name="workflow_step_status", create_type=False
    )
    workflow_event_type = postgresql.ENUM(
        "WorkflowStarted",
        "WorkflowStepStarted",
        "WorkflowStepCompleted",
        "WorkflowCompleted",
        "WorkflowFailed",
        name="workflow_event_type", create_type=False
    )

    bind = op.get_bind()
    workflow_step_type.create(bind, checkfirst=True)
    workflow_run_status.create(bind, checkfirst=True)
    workflow_step_status.create(bind, checkfirst=True)
    workflow_event_type.create(bind, checkfirst=True)

    # ---- workflows ----
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_os_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_os.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("workflow_metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_os_id", "code", name="uq_workflow_agent_os_code"),
    )
    op.create_index("ix_workflows_agent_os_id", "workflows", ["agent_os_id"])
    op.create_index("ix_workflows_code", "workflows", ["code"])
    op.create_index("ix_workflows_deleted_at", "workflows", ["deleted_at"])

    # ---- workflow_steps ----
    op.create_table(
        "workflow_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("step_type", workflow_step_type, nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True),
        sa.Column("step_config", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("workflow_id", "step_order", name="uq_workflow_step_order"),
    )
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])
    op.create_index("ix_workflow_steps_agent_id", "workflow_steps", ["agent_id"])
    op.create_index("ix_workflow_steps_team_id", "workflow_steps", ["team_id"])

    # ---- workflow_runs ----
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", workflow_run_status, nullable=False),
        sa.Column("input", sa.Text, nullable=False),
        sa.Column("result", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index("ix_workflow_runs_session_id", "workflow_runs", ["session_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    # ---- workflow_run_steps ----
    op.create_table(
        "workflow_run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_step_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("status", workflow_step_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input", postgresql.JSONB, nullable=True),
        sa.Column("output", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workflow_run_steps_workflow_run_id", "workflow_run_steps", ["workflow_run_id"])
    op.create_index("ix_workflow_run_steps_workflow_step_id", "workflow_run_steps", ["workflow_step_id"])
    op.create_index("ix_workflow_run_steps_status", "workflow_run_steps", ["status"])
    op.create_index(
        "ix_workflow_run_steps_run_order", "workflow_run_steps", ["workflow_run_id", "step_order"]
    )

    # ---- workflow_events ----
    op.create_table(
        "workflow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", workflow_event_type, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workflow_events_workflow_run_id", "workflow_events", ["workflow_run_id"])
    op.create_index("ix_workflow_events_event_type", "workflow_events", ["event_type"])
    op.create_index(
        "ix_workflow_events_run_created", "workflow_events", ["workflow_run_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("workflow_events")
    op.drop_table("workflow_run_steps")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_steps")
    op.drop_table("workflows")

    bind = op.get_bind()
    postgresql.ENUM(name="workflow_event_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="workflow_step_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="workflow_run_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="workflow_step_type").drop(bind, checkfirst=True)
