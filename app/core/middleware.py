"""
Request middleware.

Two responsibilities, both purely mechanical:

1. Correlation ID: read X-Correlation-ID if present, else generate one,
   bind it into structlog's contextvars and the response headers.

2. Auth propagation capture: read Authorization / X-API-Key from the
   inbound request and stash them in a request-scoped context
   (app.core.auth_context) so the MCP Gateway client can forward them
   later in the request lifecycle. This middleware NEVER inspects,
   decodes, or validates the credential values - see
   app/core/auth_context.py for the rationale.
"""
from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.auth_context import PropagatedAuth, set_propagated_auth
from app.core.config import get_settings
from app.core.logging import correlation_id_var


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()

        correlation_id = request.headers.get(settings.FORWARD_HEADER_CORRELATION_ID) or str(uuid.uuid4())
        correlation_id_var.set(correlation_id)
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        auth = PropagatedAuth(
            authorization=request.headers.get(settings.FORWARD_HEADER_AUTHORIZATION),
            api_key=request.headers.get(settings.FORWARD_HEADER_API_KEY),
            correlation_id=correlation_id,
        )
        set_propagated_auth(auth)

        response = await call_next(request)
        response.headers[settings.FORWARD_HEADER_CORRELATION_ID] = correlation_id
        return response
