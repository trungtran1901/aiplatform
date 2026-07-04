"""Domain-level exceptions, mapped to HTTP responses in app/main.py."""
from __future__ import annotations


class AgnoRuntimeError(Exception):
    """Base class for all domain errors raised by the platform."""

    http_status: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AgnoRuntimeError):
    http_status = 404
    error_code = "not_found"


class ConflictError(AgnoRuntimeError):
    http_status = 409
    error_code = "conflict"


class ValidationFailedError(AgnoRuntimeError):
    http_status = 422
    error_code = "validation_failed"


class CapabilityResolutionError(AgnoRuntimeError):
    """Raised when the intersection of capabilities cannot be computed
    (e.g. referenced AgentOS/Team/Agent is disabled or missing)."""

    http_status = 422
    error_code = "capability_resolution_failed"


class MCPGatewayError(AgnoRuntimeError):
    """Raised when the MCP Gateway call fails at the transport level.

    This is NOT used for authorization failures - a 401/403 from the
    Gateway is surfaced as a normal tool result/error to the agent, since
    the runtime does not interpret authorization outcomes. This exception
    is for network failures, timeouts, and malformed Gateway responses.
    """

    http_status = 502
    error_code = "mcp_gateway_error"


class RuntimeExecutionError(AgnoRuntimeError):
    """Raised when the Agno agent/team execution itself fails unexpectedly."""

    http_status = 500
    error_code = "runtime_execution_failed"
