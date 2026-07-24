"""add quota_policies + quota_usage_events tables, cost columns on model_registry

Revision ID: 0016_quota_management
Revises: 0015_workflow_schedule_webhook
Create Date: 2026-07-24

Purely additive, feature-flagged behind FEATURE_QUOTA_MANAGEMENT (off by
default - see app/core/config.py). Two new tables:

  quota_policies      - metadata (soft-deletable), WHAT limit applies to
                         WHICH scope (GLOBAL | GROUP | USER).
  quota_usage_events   - append-only audit trail, WHAT was actually
                         consumed per run.

Also adds two nullable cost columns to model_registry so QuotaMetric.
COST_USD policies can be evaluated - NULL means "cost tracking not
configured for this model", which QuotaService treats as "cost metric
not enforceable for this model" rather than an error.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_quota_management"
down_revision = "0015_workflow_schedule_webhook"
branch_labels = None
depends_on = None


def upgrade() -> None:
    scope_type = postgresql.ENUM("GLOBAL", "GROUP", "USER", name="quota_scope_type", create_type=False)
    period = postgresql.ENUM("DAILY", "MONTHLY", "FIXED_WINDOW", name="quota_period", create_type=False)
    metric = postgresql.ENUM("REQUESTS", "TOKENS", "COST_USD", name="quota_metric", create_type=False)
    bind = op.get_bind()
    scope_type.create(bind, checkfirst=True)
    period.create(bind, checkfirst=True)
    metric.create(bind, checkfirst=True)

    # ---- cost columns on model_registry (additive, nullable) ----
    op.add_column("model_registry", sa.Column("cost_per_1k_input_tokens", sa.Float(), nullable=True))
    op.add_column("model_registry", sa.Column("cost_per_1k_output_tokens", sa.Float(), nullable=True))

    # ---- quota_policies ----
    op.create_table(
        "quota_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope_type", scope_type, nullable=False),
        sa.Column("scope_value", sa.String(255), nullable=False, server_default=""),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_registry.id", ondelete="CASCADE"), nullable=True),
        sa.Column("metric", metric, nullable=False),
        sa.Column("period", period, nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=True),
        sa.Column("limit_value", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "scope_type", "scope_value", "model_id", "metric", "period",
            name="uq_quota_policy_scope",
        ),
    )
    op.create_index("ix_quota_policies_scope_type", "quota_policies", ["scope_type"])
    op.create_index("ix_quota_policies_scope_value", "quota_policies", ["scope_value"])
    op.create_index("ix_quota_policies_model_id", "quota_policies", ["model_id"])
    op.create_index("ix_quota_policies_deleted_at", "quota_policies", ["deleted_at"])

    # ---- quota_usage_events ----
    op.create_table(
        "quota_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("groups", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_registry.id", ondelete="SET NULL"), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_quota_usage_events_run_id", "quota_usage_events", ["run_id"])
    op.create_index("ix_quota_usage_events_user_id", "quota_usage_events", ["user_id"])
    op.create_index("ix_quota_usage_events_model_id", "quota_usage_events", ["model_id"])
    op.create_index("ix_quota_usage_events_user_created", "quota_usage_events", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("quota_usage_events")
    op.drop_table("quota_policies")
    op.drop_column("model_registry", "cost_per_1k_output_tokens")
    op.drop_column("model_registry", "cost_per_1k_input_tokens")

    bind = op.get_bind()
    postgresql.ENUM(name="quota_metric").drop(bind, checkfirst=True)
    postgresql.ENUM(name="quota_period").drop(bind, checkfirst=True)
    postgresql.ENUM(name="quota_scope_type").drop(bind, checkfirst=True)