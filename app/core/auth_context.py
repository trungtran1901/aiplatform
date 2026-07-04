"""
Auth propagation context.

CRITICAL DESIGN RULE (see project spec "AUTH PROPAGATION"):
Agno Runtime NEVER validates, decodes, or makes authorization decisions
based on inbound credentials. It only captures the raw header value(s)
from the incoming request and stores them in a request-scoped context so
that the MCP Gateway client can forward them, byte-for-byte, on every
downstream tool execution call.

Do not add JWT decoding, role checks, or permission logic to this module.
That responsibility belongs entirely to MCP Gateway.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PropagatedAuth:
    """Raw, unvalidated credential material captured from the inbound request."""

    authorization: str | None = None
    api_key: str | None = None
    correlation_id: str | None = None

    def as_forward_headers(self) -> dict[str, str]:
        """Build the exact header set to attach to the outbound MCP Gateway call.

        Values are forwarded verbatim - no transformation, no re-signing,
        no decoding.
        """
        headers: dict[str, str] = {}
        if self.authorization:
            headers["Authorization"] = self.authorization
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.correlation_id:
            headers["X-Correlation-ID"] = self.correlation_id
        return headers

    @property
    def has_credentials(self) -> bool:
        return bool(self.authorization or self.api_key)


_auth_ctx: ContextVar[PropagatedAuth | None] = ContextVar("propagated_auth", default=None)


def set_propagated_auth(auth: PropagatedAuth) -> None:
    _auth_ctx.set(auth)


def get_propagated_auth() -> PropagatedAuth:
    """Returns the current request's propagated auth, or an empty one.

    An empty PropagatedAuth (no credentials) is a valid state - e.g. for
    health checks or admin metadata endpoints that don't call MCP Gateway.
    The MCP Gateway itself decides what to do with missing credentials;
    the runtime does not pre-emptively reject the request.
    """
    return _auth_ctx.get() or PropagatedAuth()
