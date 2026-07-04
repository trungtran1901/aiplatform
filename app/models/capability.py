"""Capability assignment at the 3 hierarchy levels.

MCP Gateway is the single source of truth for which capability codes
*exist*. These tables only record which capability codes are *assigned*
(allow-listed) at each level. The effective allowed-tool set for a given
agent run is computed as the intersection of all three sets - see
app/services/capability_service.py.
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentOSCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_os_capabilities"
    __table_args__ = (
        UniqueConstraint("agent_os_id", "capability_code", name="uq_agent_os_capability"),
    )

    agent_os_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_os.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_code: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    agent_os: Mapped["AgentOS"] = relationship(back_populates="capability_assignments")


class TeamCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "team_capabilities"
    __table_args__ = (UniqueConstraint("team_id", "capability_code", name="uq_team_capability"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_code: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    team: Mapped["Team"] = relationship(back_populates="capability_assignments")


class AgentCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_capabilities"
    __table_args__ = (UniqueConstraint("agent_id", "capability_code", name="uq_agent_capability"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_code: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    agent: Mapped["Agent"] = relationship(back_populates="capability_assignments")
