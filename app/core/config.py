"""
Centralized application settings.

All configuration is loaded from environment variables (see .env.example).
Nothing here is hardcoded business metadata - this file only configures
infrastructure (DB, Redis, MCP Gateway endpoint, observability, auth header
names). All *agent* metadata lives in the database and is managed via the
API surfaces defined in app/api/v1.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App identity ---
    APP_NAME: str = "agno-runtime-platform"
    APP_ENV: Literal["local", "development", "staging", "production"] = "local"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # --- HTTP server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8080

    # --- Database ---
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://agno:agno@localhost:5432/agno_runtime",
        description="Async SQLAlchemy connection string (asyncpg driver).",
    )
    DATABASE_URL_SYNC: str = Field(
        default="postgresql+psycopg2://agno:agno@localhost:5432/agno_runtime",
        description="Sync connection string, used by Alembic migrations.",
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_EVENT_STREAM_TTL_SECONDS: int = 3600
    # --- Storage (MinIO) ---
    STORAGE_PROVIDER: str = "minio"
    MINIO_ENDPOINT: str = "http://localhost:9000"
    MINIO_ACCESS_KEY: str = "admin"
    MINIO_SECRET_KEY: str = ""
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "knowledge-platform"
    FEATURE_WORKFLOW_SCHEDULING: bool = False
    FEATURE_WORKFLOW_WEBHOOKS: bool = False
    WORKFLOW_SCHEDULER_TICK_SECONDS: int = 30
    WORKFLOW_SCHEDULER_LOCK_TTL_SECONDS: int = 60
    # --- OCR Service ---
    OCR_SERVICE_URL: str = "http://localhost:8003"
    OCR_TIMEOUT_SECONDS: float = 60.0
    # --- MCP Gateway ---
    # MCP Gateway Core exposes a real MCP server over SSE (its
    # `mcp_server/` package, default port 8100, path /sse). Agno Runtime
    # connects as an MCP client - it never enforces authorization itself,
    # it only forwards the inbound Authorization / X-API-Key header
    # verbatim as SSE connection headers.
    MCP_GATEWAY_SSE_URL: str = Field(
        default="http://localhost:8100/sse",
        description="Full URL of MCP Gateway's MCP-over-SSE endpoint.",
    )
    MCP_GATEWAY_TIMEOUT_SECONDS: float = 30.0

    # --- Auth propagation (NOT enforcement) ---
    # These are the header names the runtime looks for on inbound requests
    # and forwards unchanged downstream. The runtime never inspects,
    # decodes, or validates their contents.
    FORWARD_HEADER_AUTHORIZATION: str = "Authorization"
    FORWARD_HEADER_API_KEY: str = "X-API-Key"
    FORWARD_HEADER_CORRELATION_ID: str = "X-Correlation-ID"

    # --- Model providers (used only to populate / validate model_registry) ---
    DEFAULT_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None

    # --- Keycloak (token issuer reference only; runtime does not validate) ---
    KEYCLOAK_ISSUER_URL: str | None = None
    KEYCLOAK_REALM: str | None = None
    KEYCLOAK_JWKS_URL: str | None = None
    KEYCLOAK_AUDIENCE: str | None = None
    AUTH_MODE: Literal["trust_client_user_id", "keycloak_required"] = "trust_client_user_id"
    # --- Observability ---
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_SERVICE_NAME: str = "agno-runtime"

    # --- SSE / Streaming ---
    SSE_KEEPALIVE_SECONDS: int = 15

    # --- AgentX Runtime v2 feature flags ---
    # All default OFF. Existing .env files require zero changes; runtime
    # behavior is byte-for-byte identical to pre-v2 until a flag is
    # explicitly turned on. Each subsystem is independently toggleable
    # per the spec's "Feature Flags" / "Dynamic Configuration" sections.
    FEATURE_UI_METADATA_REGISTRY: bool = False
    FEATURE_BUSINESS_OBJECT_REGISTRY: bool = False
    FEATURE_CONTEXT_ENGINE: bool = False
    FEATURE_PLANNING_ENGINE: bool = False
    FEATURE_EXECUTION_ENGINE: bool = False
    FEATURE_OBSERVATION_ENGINE: bool = False
    FEATURE_EVENT_ENGINE: bool = False
    FEATURE_UI_SKILLS: bool = False
    FEATURE_UI_ACTIONS: bool = False
    FEATURE_KEYCLOAK_AUTH: bool = False
    FEATURE_QUOTA_MANAGEMENT: bool = False
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
