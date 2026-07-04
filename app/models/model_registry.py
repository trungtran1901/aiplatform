"""Model registry: no LLM model/provider is ever hardcoded in agent logic.

Supports custom base_url + api_key per entry so any OpenAI-compatible
endpoint (local models via Ollama/vLLM/LM Studio/text-generation-webui,
or any third-party OpenAI-compatible provider) can be registered without
code changes, alongside standard OpenAI/Anthropic entries.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ModelRegistry(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("provider", "model", name="uq_model_provider_model"),)

    # "openai", "anthropic", or "openai_like" (any OpenAI-compatible
    # endpoint: local models, self-hosted, or third-party providers).
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "gpt-4o-mini", "llama3.1:70b"
    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Custom endpoint support - all optional, only used when set.
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Arbitrary extra client kwargs (e.g. {"default_headers": {...}},
    # organization id, custom timeouts, etc.) merged into the underlying
    # provider client constructor.
    extra_client_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<ModelRegistry {self.provider}/{self.model} base_url={self.base_url}>"