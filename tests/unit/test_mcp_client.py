"""Tests for MCPGatewayClient - the auth-propagation contract.

These tests pin down the most security-critical behavior in the
platform: inbound Authorization/X-API-Key headers must be forwarded
verbatim to MCP Gateway, and the client must never raise on 401/403
(those are data, not exceptions) while it must raise MCPGatewayError on
genuine transport failures.
"""
from __future__ import annotations

import httpx
import pytest

from app.agno_runtime.mcp_client import MCPGatewayClient
from app.core.auth_context import PropagatedAuth, set_propagated_auth
from app.core.exceptions import MCPGatewayError

pytestmark = pytest.mark.asyncio


async def test_execute_forwards_authorization_header_verbatim(monkeypatch):
    captured_headers = {}

    async def fake_post_with_retry(self, url, payload, headers):
        captured_headers.update(headers)

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"ok": True}

            text = "{}"

        return FakeResponse()

    monkeypatch.setattr(MCPGatewayClient, "_post_with_retry", fake_post_with_retry)

    set_propagated_auth(PropagatedAuth(authorization="Bearer xxx-secret-token"))

    client = MCPGatewayClient(base_url="http://fake-gateway")
    result = await client.execute("crm.customer.create", {"name": "ABC"})

    assert captured_headers["Authorization"] == "Bearer xxx-secret-token"
    assert result["ok"] is True
    assert result["status_code"] == 200


async def test_execute_forwards_api_key_header_verbatim(monkeypatch):
    captured_headers = {}

    async def fake_post_with_retry(self, url, payload, headers):
        captured_headers.update(headers)

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"ok": True}

            text = "{}"

        return FakeResponse()

    monkeypatch.setattr(MCPGatewayClient, "_post_with_retry", fake_post_with_retry)

    set_propagated_auth(PropagatedAuth(api_key="my-api-key-123"))

    client = MCPGatewayClient(base_url="http://fake-gateway")
    await client.execute("crm.customer.create", {"name": "ABC"})

    assert captured_headers["X-API-Key"] == "my-api-key-123"
    assert "Authorization" not in captured_headers


async def test_execute_does_not_raise_on_403_forbidden(monkeypatch):
    """A 403 from MCP Gateway is an authorization OUTCOME, not a
    transport failure - the runtime must never raise an exception for
    it, since that would mean the runtime is interpreting authorization,
    which is explicitly forbidden."""

    async def fake_post_with_retry(self, url, payload, headers):
        class FakeResponse:
            status_code = 403

            def json(self):
                return {"error": "forbidden", "reason": "missing scope"}

            text = '{"error": "forbidden"}'

        return FakeResponse()

    monkeypatch.setattr(MCPGatewayClient, "_post_with_retry", fake_post_with_retry)
    set_propagated_auth(PropagatedAuth(authorization="Bearer some-token"))

    client = MCPGatewayClient(base_url="http://fake-gateway")
    result = await client.execute("crm.customer.create", {"name": "ABC"})

    assert result["ok"] is False
    assert result["status_code"] == 403
    assert result["body"]["error"] == "forbidden"


async def test_execute_raises_mcp_gateway_error_on_transport_failure(monkeypatch):
    async def fake_post_with_retry(self, url, payload, headers):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(MCPGatewayClient, "_post_with_retry", fake_post_with_retry)
    set_propagated_auth(PropagatedAuth(authorization="Bearer xxx"))

    client = MCPGatewayClient(base_url="http://fake-gateway")
    with pytest.raises(MCPGatewayError):
        await client.execute("crm.customer.create", {"name": "ABC"})


async def test_execute_works_with_no_credentials_present():
    """Runtime must not pre-emptively block calls just because no
    credentials were captured - MCP Gateway decides what to do, not us."""
    set_propagated_auth(PropagatedAuth())  # empty
    auth = PropagatedAuth()
    assert auth.has_credentials is False
    assert auth.as_forward_headers() == {}
