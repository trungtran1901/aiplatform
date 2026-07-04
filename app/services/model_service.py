"""
Model resolution service.

Resolves an Agent's model_id (falling back to AgentOS.default_model_id)
into a concrete Agno model instance. No provider/model name is ever
hardcoded in agent logic - everything is read from model_registry.

Supports custom base_url + api_key per registry entry, so local models
(Ollama, vLLM, LM Studio, text-generation-webui, etc.) and third-party
OpenAI-compatible / Anthropic-compatible providers can be registered
without any code change - just a row in model_registry.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ValidationFailedError
from app.core.logging import get_logger
from app.models.model_registry import ModelRegistry
from app.repositories.model_repository import ModelRegistryRepository

logger = get_logger(__name__)


class ModelResolutionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.model_repo = ModelRegistryRepository(session)

    async def resolve_registry_entry(
        self,
        *,
        agent_model_id: uuid.UUID | None,
        agent_os_default_model_id: uuid.UUID | None,
    ) -> ModelRegistry:
        model_id = agent_model_id or agent_os_default_model_id
        if model_id is None:
            raise ValidationFailedError(
                "No model_id resolvable: neither Agent.model_id nor AgentOS.default_model_id is set"
            )
        entry = await self.model_repo.get(model_id)
        if entry is None or not entry.enabled:
            raise ValidationFailedError(f"ModelRegistry entry {model_id} not found or disabled")
        return entry

    def build_agno_model(self, entry: ModelRegistry, *, temperature_override: float | None = None):
        """Instantiates the appropriate Agno model wrapper class based on
        the provider stored in model_registry. Imports are local to avoid
        importing every provider SDK eagerly.

        provider values:
          - "openai"      -> agno.models.openai.OpenAIChat (official OpenAI API)
          - "openai_like"  -> agno.models.openai.like.OpenAILike (any
                              OpenAI-compatible endpoint: local models via
                              Ollama/vLLM/LM Studio, or third-party providers).
                              Set entry.base_url to point at it.
          - "anthropic"    -> agno.models.anthropic.Claude (official Anthropic
                              API, or any Anthropic-compatible endpoint via
                              entry.base_url, forwarded through client_params).
        """
        settings = get_settings()
        temperature = temperature_override if temperature_override is not None else entry.temperature
        extra_params = entry.extra_client_params or {}

        provider = entry.provider.lower()

        if provider == "openai":
            from agno.models.openai import OpenAIChat

            return OpenAIChat(
                id=entry.model,
                temperature=temperature,
                max_tokens=entry.max_tokens,
                api_key=entry.api_key or settings.OPENAI_API_KEY,
                base_url=entry.base_url,  # None uses OpenAI's default endpoint
                **extra_params,
            )

        if provider == "openai_like":
            from agno.models.openai.like import OpenAILike

            if not entry.base_url:
                raise ValidationFailedError(
                    "ModelRegistry entries with provider='openai_like' require base_url "
                    "(e.g. http://localhost:11434/v1 for a local Ollama server)."
                )
            return OpenAILike(
                id=entry.model,
                name=f"openai_like:{entry.model}",
                temperature=temperature,
                max_tokens=entry.max_tokens,
                # Local/self-hosted servers frequently don't require a real
                # key - fall back to a placeholder rather than forcing one.
                api_key=entry.api_key or settings.OPENAI_API_KEY or "not-provided",
                base_url=entry.base_url,
                **extra_params,
            )

        if provider == "anthropic":
            from agno.models.anthropic import Claude

            client_params = dict(extra_params)
            if entry.base_url:
                client_params["base_url"] = entry.base_url

            return Claude(
                id=entry.model,
                temperature=temperature,
                max_tokens=entry.max_tokens,
                api_key=entry.api_key or settings.ANTHROPIC_API_KEY,
                client_params=client_params or None,
            )

        raise ValidationFailedError(
            f"Unsupported model provider in registry: {entry.provider!r}. "
            "Use 'openai', 'anthropic', or 'openai_like' (for local/custom OpenAI-compatible endpoints)."
        )