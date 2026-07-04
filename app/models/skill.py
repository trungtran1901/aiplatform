"""Skill management: reusable capability groups, mapped to capability codes
sourced from MCP Gateway, and assigned to agents."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CodeMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Skill(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A named, reusable bundle of capabilities + behavioral instructions.

    E.g. skill 'customer-management' bundles capability codes like
    'crm.customer.create', 'crm.customer.search' plus instructions
    describing how/when an agent should invoke them.
    """

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("code", name="uq_skill_code"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    capability_links: Mapped[list["SkillCapability"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )
    agent_links: Mapped[list["AgentSkill"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Skill code={self.code}>"


class SkillCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """skill_capabilities: maps a Skill to a capability_code known to MCP Gateway."""

    __tablename__ = "skill_capabilities"
    __table_args__ = (UniqueConstraint("skill_id", "capability_code", name="uq_skill_capability"),)

    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_code: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    skill: Mapped["Skill"] = relationship(back_populates="capability_links")


class AgentSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """agent_skills: assigns a Skill (and therefore its capability bundle) to an Agent."""

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
