"""add skill_type + config to skills (Knowledge Skill support)

Revision ID: 0007_knowledge_skills
Revises: 0006_agno_team_sessions
Create Date: 2026-07-04

Extends the existing Skill Registry (skills table) to support pluggable
Skill *types* rather than only MCP-capability bundles. Per
docs/Knowledge.md: Knowledge is modeled as just another Skill type
(KNOWLEDGE), executed by app/knowledge/executor.py::KnowledgeSkillExecutor,
never embedded directly into Agent. The runtime never knows how a given
Skill type is implemented internally - it only knows how to dispatch to
the right executor based on `skill_type`.

Two new columns, both additive/backward-compatible:

  skill_type   - enum, defaults to 'MCP' for every pre-existing row
                 (every Skill created before this migration was
                 implicitly an MCP-capability bundle)
  config       - JSONB, free-form per-type configuration (e.g. for
                 KNOWLEDGE: knowledgeBaseUrl, searchApi, collectionId,
                 agentId, embeddingModelCode, topK, timeout, stream).
                 NULL for MCP skills, which continue to be configured
                 entirely via skill_capabilities/agent_skills as before.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_knowledge_skills"
down_revision = "0006_agno_team_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    skill_type = postgresql.ENUM(
        "MCP", "WORKFLOW", "PROMPT", "CUSTOM", "KNOWLEDGE", name="skill_type", create_type=False
    )
    bind = op.get_bind()
    skill_type.create(bind, checkfirst=True)

    op.add_column(
        "skills",
        sa.Column("skill_type", skill_type, nullable=False, server_default="MCP"),
    )
    op.add_column("skills", sa.Column("config", postgresql.JSONB(), nullable=True))
    op.create_index("ix_skills_skill_type", "skills", ["skill_type"])

    # Drop the server_default after backfilling existing rows - new rows
    # must explicitly choose a type going forward (enforced by the
    # Pydantic schema, defaulting to MCP for backward compatibility with
    # existing SkillCreate payloads that don't send a type at all).
    op.alter_column("skills", "skill_type", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_skills_skill_type", table_name="skills")
    op.drop_column("skills", "config")
    op.drop_column("skills", "skill_type")

    bind = op.get_bind()
    postgresql.ENUM(name="skill_type").drop(bind, checkfirst=True)
