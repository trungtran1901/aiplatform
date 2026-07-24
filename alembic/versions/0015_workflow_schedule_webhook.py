"""add workflow_schedules + workflow_webhooks tables

Revision ID: 0014_workflow_schedule_webhook
Revises: 0013_execution_engine
Create Date: 2026-07-23

Purely additive: two new tables, each FK'd to workflows (CASCADE), no
existing table/column/enum touched. Safe no-op for any deployment that
keeps FEATURE_WORKFLOW_SCHEDULING / FEATURE_WORKFLOW_WEBHOOKS off.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015_workflow_schedule_webhook"
down_revision = "0014_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schedule_type = postgresql.ENUM("CRON", "INTERVAL", name="schedule_type", create_type=False)
    bind = op.get_bind()
    schedule_type.create(bind, checkfirst=True)

    # ---- workflow_schedules ----
    op.create_table(
        "workflow_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_type", schedule_type, nullable=False),
        sa.Column("cron_expression", sa.String(128), nullable=True),
        sa.Column("interval_seconds", sa.Integer, nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("input_template", sa.Text, nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("last_workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_schedules_workflow_id", "workflow_schedules", ["workflow_id"])
    op.create_index("ix_workflow_schedules_next_run_at", "workflow_schedules", ["next_run_at"])
    op.create_index("ix_workflow_schedules_deleted_at", "workflow_schedules", ["deleted_at"])

    # ---- workflow_webhooks ----
    op.create_table(
        "workflow_webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("webhook_token", sa.String(64), nullable=False),
        sa.Column("secret", sa.Text, nullable=True),
        sa.Column("input_field_path", sa.String(255), nullable=True),
        sa.Column("allowed_source_ips", postgresql.JSONB, nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("webhook_token", name="uq_workflow_webhook_token"),
    )
    op.create_index("ix_workflow_webhooks_workflow_id", "workflow_webhooks", ["workflow_id"])
    op.create_index("ix_workflow_webhooks_webhook_token", "workflow_webhooks", ["webhook_token"])
    op.create_index("ix_workflow_webhooks_deleted_at", "workflow_webhooks", ["deleted_at"])


def downgrade() -> None:
    op.drop_table("workflow_webhooks")
    op.drop_table("workflow_schedules")
    bind = op.get_bind()
    postgresql.ENUM(name="schedule_type").drop(bind, checkfirst=True)