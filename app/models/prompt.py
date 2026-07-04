"""Prompt management. Prompts are composed at runtime: AgentOS + Team + Agent."""
from __future__ import annotations

from enum import Enum

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CodeMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PromptStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class Prompt(UUIDPrimaryKeyMixin, CodeMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_prompt_code_version"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[PromptStatus] = mapped_column(
        SAEnum(PromptStatus, name="prompt_status"), default=PromptStatus.draft, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Prompt code={self.code} v{self.version} status={self.status}>"
