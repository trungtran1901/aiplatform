"""Layer 1/2/3 of the Agno hierarchy: AgentOS -> Teams -> Agents."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CodeMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AgentOS(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Layer 1: top-level container. Represents a product/tenant boundary.

    Holds shared prompt, shared MCP Gateway capability scope, and default
    model used as a fallback by Teams/Agents beneath it.
    """

    __tablename__ = "agent_os"
    __table_args__ = (UniqueConstraint("code", name="uq_agent_os_code"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_registry.id"), nullable=True
    )
    shared_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    teams: Mapped[list["Team"]] = relationship(
        back_populates="agent_os", cascade="all, delete-orphan"
    )
    default_model: Mapped["ModelRegistry"] = relationship(foreign_keys=[default_model_id])
    shared_prompt: Mapped["Prompt"] = relationship(foreign_keys=[shared_prompt_id])
    capability_assignments: Mapped[list["AgentOSCapability"]] = relationship(
        back_populates="agent_os", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AgentOS code={self.code} enabled={self.enabled}>"


class Team(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Layer 2: orchestrates a group of agents. Maps onto Agno's Team construct."""

    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("agent_os_id", "code", name="uq_team_agent_os_code"),)

    agent_os_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_os.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    agent_os: Mapped["AgentOS"] = relationship(back_populates="teams")
    agents: Mapped[list["Agent"]] = relationship(back_populates="team", cascade="all, delete-orphan")
    team_prompt: Mapped["Prompt"] = relationship(foreign_keys=[team_prompt_id])
    capability_assignments: Mapped[list["TeamCapability"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Team code={self.code} agent_os_id={self.agent_os_id}>"


class Agent(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Layer 3: executes reasoning, tool calling, and memory usage via Agno."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("team_id", "code", name="uq_agent_team_code"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_registry.id"), nullable=True
    )
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    team: Mapped["Team"] = relationship(back_populates="agents")
    prompt: Mapped["Prompt"] = relationship(foreign_keys=[prompt_id])
    model: Mapped["ModelRegistry"] = relationship(foreign_keys=[model_id])
    capability_assignments: Mapped[list["AgentCapability"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    skill_links: Mapped[list["AgentSkill"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Agent code={self.code} team_id={self.team_id}>"
