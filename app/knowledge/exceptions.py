"""Knowledge Skill error hierarchy.

Mirrors app.core.exceptions.AgnoRuntimeError's shape (http_status +
error_code) so these can be raised straight through FastAPI's existing
AgnoRuntimeError exception handler (app/main.py) without any new
handler wiring, while staying a distinct hierarchy so callers that only
care about Knowledge failures (e.g. KnowledgeSkillExecutor's caller
inside engine.py, which must never let a Knowledge failure crash an
Agent run - see docs/Knowledge.md "Error Handling") can catch just
`KnowledgeServiceError`.
"""
from __future__ import annotations

from app.core.exceptions import AgnoRuntimeError


class KnowledgeServiceError(AgnoRuntimeError):
    """Base class for all Knowledge Skill failures."""

    http_status = 502
    error_code = "knowledge_service_error"


class KnowledgeConfigError(KnowledgeServiceError):
    """The Skill's `config` is missing/invalid (bad collection id,
    missing knowledgeBaseUrl, etc.) - a configuration problem, not a
    transport problem."""

    http_status = 422
    error_code = "knowledge_config_error"


class KnowledgeTimeoutError(KnowledgeServiceError):
    """The Knowledge Platform did not respond within `config.timeout`
    seconds."""

    http_status = 504
    error_code = "knowledge_timeout"


class KnowledgeUnavailableError(KnowledgeServiceError):
    """The Knowledge Platform could not be reached at all (connection
    refused, DNS failure, non-2xx response)."""

    http_status = 502
    error_code = "knowledge_unavailable"
