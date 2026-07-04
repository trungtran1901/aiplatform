"""add base_url/api_key/extra_client_params to model_registry

Revision ID: 0002_model_registry_base_url
Revises: 0001_initial_schema
Create Date: 2026-06-20

Adds support for custom endpoints (local models via Ollama/vLLM/LM
Studio, or third-party OpenAI-compatible / Anthropic-compatible
providers) directly through model_registry, with no code changes
required - just a new row.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_model_registry_base_url"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_registry", sa.Column("base_url", sa.Text(), nullable=True))
    op.add_column("model_registry", sa.Column("api_key", sa.Text(), nullable=True))
    op.add_column(
        "model_registry",
        sa.Column("extra_client_params", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_registry", "extra_client_params")
    op.drop_column("model_registry", "api_key")
    op.drop_column("model_registry", "base_url")