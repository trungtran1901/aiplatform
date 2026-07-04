"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-20

Creates the complete Agno Runtime Platform schema:
  - model_registry, prompts (no FK dependencies)
  - agent_os (FKs -> model_registry, prompts)
  - teams (FK -> agent_os, prompts)
  - agents (FK -> teams, prompts, model_registry)
  - skills, skill_capabilities, agent_skills
  - agent_os_capabilities, team_capabilities, agent_capabilities
  - chat_sessions, chat_messages
  - agent_runs, agent_events
  - agent_memories
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- ENUM types ----
    prompt_status = postgresql.ENUM("draft", "active", "archived", name="prompt_status", create_type=False)
    message_role = postgresql.ENUM("user", "assistant", "system", "tool", name="message_role", create_type=False)
    run_status = postgresql.ENUM(
        "pending", "running", "tool_calling", "waiting", "completed", "failed", name="run_status", create_type=False
    )
    event_type = postgresql.ENUM(
        "agent_started",
        "reasoning_started",
        "tool_selected",
        "tool_call_started",
        "tool_call_completed",
        "agent_response",
        "agent_completed",
        "error",
        name="event_type",
        create_type=False
    )
    memory_type = postgresql.ENUM(
        "conversation", "summary", "fact", "preference", "working_memory", name="memory_type", create_type=False
    )

    bind = op.get_bind()
    prompt_status.create(bind, checkfirst=True)
    message_role.create(bind, checkfirst=True)
    run_status.create(bind, checkfirst=True)
    event_type.create(bind, checkfirst=True)
    memory_type.create(bind, checkfirst=True)

    # ---- model_registry ----
    op.create_table(
        "model_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("temperature", sa.Float, nullable=False),
        sa.Column("max_tokens", sa.Integer, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "model", name="uq_model_provider_model"),
    )
    op.create_index("ix_model_registry_deleted_at", "model_registry", ["deleted_at"])

    # ---- prompts ----
    op.create_table(
        "prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", prompt_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", "version", name="uq_prompt_code_version"),
    )
    op.create_index("ix_prompts_code", "prompts", ["code"])
    op.create_index("ix_prompts_deleted_at", "prompts", ["deleted_at"])

    # ---- agent_os ----
    op.create_table(
        "agent_os",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("default_model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_registry.id"), nullable=True),
        sa.Column("shared_prompt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prompts.id"), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_agent_os_code"),
    )
    op.create_index("ix_agent_os_code", "agent_os", ["code"])
    op.create_index("ix_agent_os_deleted_at", "agent_os", ["deleted_at"])

    # ---- teams ----
    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_os_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_os.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("team_prompt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prompts.id"), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_os_id", "code", name="uq_team_agent_os_code"),
    )
    op.create_index("ix_teams_agent_os_id", "teams", ["agent_os_id"])
    op.create_index("ix_teams_code", "teams", ["code"])
    op.create_index("ix_teams_deleted_at", "teams", ["deleted_at"])

    # ---- agents ----
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("prompt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prompts.id"), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_registry.id"), nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("team_id", "code", name="uq_agent_team_code"),
    )
    op.create_index("ix_agents_team_id", "agents", ["team_id"])
    op.create_index("ix_agents_code", "agents", ["code"])
    op.create_index("ix_agents_deleted_at", "agents", ["deleted_at"])

    # ---- skills ----
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("instructions", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_skill_code"),
    )
    op.create_index("ix_skills_code", "skills", ["code"])
    op.create_index("ix_skills_deleted_at", "skills", ["deleted_at"])

    # ---- skill_capabilities ----
    op.create_table(
        "skill_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_code", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("skill_id", "capability_code", name="uq_skill_capability"),
    )
    op.create_index("ix_skill_capabilities_skill_id", "skill_capabilities", ["skill_id"])
    op.create_index("ix_skill_capabilities_capability_code", "skill_capabilities", ["capability_code"])

    # ---- agent_skills ----
    op.create_table(
        "agent_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("agent_id", "skill_id", name="uq_agent_skill"),
    )
    op.create_index("ix_agent_skills_agent_id", "agent_skills", ["agent_id"])
    op.create_index("ix_agent_skills_skill_id", "agent_skills", ["skill_id"])

    # ---- agent_os_capabilities ----
    op.create_table(
        "agent_os_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_os_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_os.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_code", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("agent_os_id", "capability_code", name="uq_agent_os_capability"),
    )
    op.create_index("ix_agent_os_capabilities_agent_os_id", "agent_os_capabilities", ["agent_os_id"])
    op.create_index("ix_agent_os_capabilities_capability_code", "agent_os_capabilities", ["capability_code"])

    # ---- team_capabilities ----
    op.create_table(
        "team_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_code", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("team_id", "capability_code", name="uq_team_capability"),
    )
    op.create_index("ix_team_capabilities_team_id", "team_capabilities", ["team_id"])
    op.create_index("ix_team_capabilities_capability_code", "team_capabilities", ["capability_code"])

    # ---- agent_capabilities ----
    op.create_table(
        "agent_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_code", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("agent_id", "capability_code", name="uq_agent_capability"),
    )
    op.create_index("ix_agent_capabilities_agent_id", "agent_capabilities", ["agent_id"])
    op.create_index("ix_agent_capabilities_capability_code", "agent_capabilities", ["capability_code"])

    # ---- chat_sessions ----
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_os_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_os.id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("context", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_sessions_agent_os_id", "chat_sessions", ["agent_os_id"])
    op.create_index("ix_chat_sessions_team_id", "chat_sessions", ["team_id"])
    op.create_index("ix_chat_sessions_agent_id", "chat_sessions", ["agent_id"])
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_deleted_at", "chat_sessions", ["deleted_at"])

    # ---- agent_runs ----
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("input", sa.Text, nullable=False),
        sa.Column("output", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
    op.create_index("ix_agent_runs_agent_id", "agent_runs", ["agent_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_session_created", "agent_runs", ["session_id", "created_at"])

    # ---- chat_messages ----
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("message_metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_run_id", "chat_messages", ["run_id"])
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])

    # ---- agent_events ----
    op.create_table(
        "agent_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_events_run_id", "agent_events", ["run_id"])
    op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])
    op.create_index("ix_agent_events_run_created", "agent_events", ["run_id", "created_at"])

    # ---- agent_memories ----
    op.create_table(
        "agent_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("memory_type", memory_type, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_memories_agent_id", "agent_memories", ["agent_id"])
    op.create_index("ix_agent_memories_user_id", "agent_memories", ["user_id"])
    op.create_index("ix_agent_memories_memory_type", "agent_memories", ["memory_type"])


def downgrade() -> None:
    op.drop_table("agent_memories")
    op.drop_table("agent_events")
    op.drop_table("chat_messages")
    op.drop_table("agent_runs")
    op.drop_table("chat_sessions")
    op.drop_table("agent_capabilities")
    op.drop_table("team_capabilities")
    op.drop_table("agent_os_capabilities")
    op.drop_table("agent_skills")
    op.drop_table("skill_capabilities")
    op.drop_table("skills")
    op.drop_table("agents")
    op.drop_table("teams")
    op.drop_table("agent_os")
    op.drop_table("prompts")
    op.drop_table("model_registry")

    bind = op.get_bind()
    postgresql.ENUM(name="memory_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="event_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="run_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="message_role").drop(bind, checkfirst=True)
    postgresql.ENUM(name="prompt_status").drop(bind, checkfirst=True)
