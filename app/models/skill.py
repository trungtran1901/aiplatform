"""Skill management: reusable capability groups, mapped to capability codes
sourced from MCP Gateway, and assigned to agents.

Extended (see alembic/versions/0007_knowledge_skills.py, docs/Knowledge.md)
to support pluggable Skill *types*, not just MCP-capability bundles.
`skill_type` decides which Executor runs when an Agent invokes this
Skill; `config` is free-form, type-specific configuration (e.g. a
KNOWLEDGE skill's `knowledgeBaseUrl`, `collectionId`, etc.) that this
model has zero opinion about the shape of - validation of `config`'s
contents lives in the schema layer (app/schemas/skill.py) and the
relevant executor (app/knowledge/models.py for KNOWLEDGE), never here.
"""
from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CodeMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SkillType(str, Enum):
    """What kind of Executor a Skill dispatches to at run time.

    MCP        - existing behavior: a bundle of capability codes,
                 executed via MCP Gateway (skill_capabilities table).
    WORKFLOW   - reserved for a future Skill that triggers a Workflow.
    PROMPT     - reserved for a future pure prompt-injection Skill.
    CUSTOM     - reserved escape hatch for bespoke executors.
    KNOWLEDGE  - executed by app.knowledge.executor.KnowledgeSkillExecutor
                 against an external Knowledge Platform microservice,
                 entirely configured via `config` (see
                 app/knowledge/models.py::KnowledgeSkillConfig).
    """

    mcp = "MCP"
    workflow = "WORKFLOW"
    prompt = "PROMPT"
    custom = "CUSTOM"
    knowledge = "KNOWLEDGE"


class Skill(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A named, reusable bundle of capabilities + behavioral instructions,
    or (for non-MCP types) a pluggable Skill Executor's configuration.

    E.g. skill 'customer-management' (skill_type=MCP) bundles capability
    codes like 'crm.customer.create' plus instructions describing how/
    when an agent should invoke them. Skill 'hr_policy_search'
    (skill_type=KNOWLEDGE) instead carries a `config` blob describing
    which Knowledge Platform instance/collection to query - it has no
    capability_links at all.
    """

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("code", name="uq_skill_code"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_type: Mapped[SkillType] = mapped_column(
        SAEnum(SkillType, name="skill_type", values_callable=lambda obj: [e.value for e in obj]),
        default=SkillType.mcp,
        nullable=False,
        index=True,
    )
    # Free-form, skill_type-specific configuration. NULL for MCP skills
    # (which configure entirely via skill_capabilities/agent_skills).
    # For KNOWLEDGE skills, validated against
    # app.knowledge.models.KnowledgeSkillConfig at the schema/service
    # boundary, never enforced at the DB layer - keeps this table
    # agnostic to any one executor's schema.
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    capability_links: Mapped[list["SkillCapability"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )
    agent_links: Mapped[list["AgentSkill"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Skill code={self.code} type={self.skill_type}>"


class SkillCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """skill_capabilities: maps a Skill to a capability_code known to MCP Gateway.

    Only meaningful for skill_type=MCP - other Skill types (e.g.
    KNOWLEDGE) have no rows here and contribute zero MCP capability
    codes, per capability_service's union-of-skill-capabilities logic.
    """

    __tablename__ = "skill_capabilities"
    __table_args__ = (UniqueConstraint("skill_id", "capability_code", name="uq_skill_capability"),)

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_code: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    skill: Mapped["Skill"] = relationship(back_populates="capability_links")


class AgentSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """agent_skills: assigns a Skill (of any skill_type) to an Agent."""

    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("agent_id", "skill_id", name="uq_agent_skill"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )

    agent: Mapped["Agent"] = relationship(back_populates="skill_links")
    skill: Mapped["Skill"] = relationship(back_populates="agent_links")
