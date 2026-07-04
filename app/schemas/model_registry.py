from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class ModelRegistryBase(BaseModel):
    provider: str = Field(
        ..., min_length=1, max_length=64,
        description="'openai', 'anthropic', or 'openai_like' for any OpenAI-compatible endpoint "
                    "(local models via Ollama/vLLM/LM Studio, or third-party providers).",
    )
    model: str = Field(..., min_length=1, max_length=128)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=200_000)
    enabled: bool = True
    base_url: str | None = Field(
        default=None,
        description="Custom API base URL, e.g. http://localhost:11434/v1 for a local Ollama server, "
                    "or any OpenAI-compatible / Anthropic-compatible provider endpoint.",
    )
    api_key: str | None = Field(
        default=None,
        description="Per-entry API key. If omitted, falls back to OPENAI_API_KEY / ANTHROPIC_API_KEY "
                    "from environment depending on provider. Local servers often accept any placeholder value.",
    )
    extra_client_params: dict | None = Field(
        default=None,
        description="Extra kwargs merged into the underlying provider client "
                    "(e.g. {'default_headers': {...}}, organization id, custom timeouts).",
    )


class ModelRegistryCreate(ModelRegistryBase):
    pass


class ModelRegistryUpdate(BaseModel):
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    enabled: bool | None = None
    base_url: str | None = None
    api_key: str | None = None
    extra_client_params: dict | None = None


class ModelRegistryRead(TimestampedSchema, ModelRegistryBase):
    pass