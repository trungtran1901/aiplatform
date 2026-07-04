"""Tests for ToolCatalogBuilder / DynamicToolEntrypoint - verifies that
capability codes are correctly turned into callable Agno Function
objects, with no hardcoded tool definitions."""
from __future__ import annotations

import json

import pytest
from agno.tools.function import Function

from app.agno_runtime.tool_adapter import DynamicToolEntrypoint, ToolCatalogBuilder, _safe_function_name


class FakeMCPClient:
    def __init__(self, execute_result=None, capabilities=None):
        self._execute_result = execute_result or {"status_code": 200, "ok": True, "body": {"id": "cust_1"}}
        self._capabilities = capabilities or []
        self.calls = []

    async def execute(self, capability_code, arguments, run_id=None):
        self.calls.append((capability_code, arguments, run_id))
        return self._execute_result

    async def list_capabilities(self):
        return self._capabilities


def test_safe_function_name_sanitizes_dots_and_dashes():
    assert _safe_function_name("crm.customer.create") == "crm_customer_create"
    assert _safe_function_name("erp-invoice-create") == "erp_invoice_create"


@pytest.mark.asyncio
async def test_build_creates_one_function_per_capability_code():
    client = FakeMCPClient()
    builder = ToolCatalogBuilder(client)

    tools = await builder.build(["crm.customer.create", "crm.customer.search"])

    assert len(tools) == 2
    assert all(isinstance(t, Function) for t in tools)
    names = {t.name for t in tools}
    assert names == {"crm_customer_create", "crm_customer_search"}


@pytest.mark.asyncio
async def test_build_uses_generic_schema_when_no_discovery_available():
    client = FakeMCPClient(capabilities=[])  # discovery returns nothing
    builder = ToolCatalogBuilder(client)

    tools = await builder.build(["crm.customer.create"])
    assert tools[0].parameters["type"] == "object"
    assert "arguments" in tools[0].parameters["properties"]


@pytest.mark.asyncio
async def test_build_uses_real_schema_when_discovery_provides_one():
    client = FakeMCPClient(
        capabilities=[
            {
                "code": "crm.customer.create",
                "description": "Creates a customer record",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            }
        ]
    )
    builder = ToolCatalogBuilder(client)

    tools = await builder.build(["crm.customer.create"])
    assert tools[0].description == "Creates a customer record"
    assert "name" in tools[0].parameters["properties"]


@pytest.mark.asyncio
async def test_entrypoint_calls_mcp_client_execute_with_run_id():
    client = FakeMCPClient()
    entrypoint = DynamicToolEntrypoint("crm.customer.create", client, run_id="run-123")

    result = await entrypoint(name="ABC Corp")

    assert client.calls == [("crm.customer.create", {"name": "ABC Corp"}, "run-123")]
    parsed = json.loads(result)
    assert parsed == {"id": "cust_1"}


@pytest.mark.asyncio
async def test_entrypoint_normalizes_generic_arguments_wrapper():
    """When the LLM used the generic fallback schema, it sends a single
    `arguments` kwarg wrapping the real payload - the entrypoint should
    unwrap that before forwarding to MCP Gateway."""
    client = FakeMCPClient()
    entrypoint = DynamicToolEntrypoint("crm.customer.create", client)

    await entrypoint(arguments={"name": "ABC Corp"})

    assert client.calls[0][1] == {"name": "ABC Corp"}


@pytest.mark.asyncio
async def test_entrypoint_surfaces_error_without_raising_on_non_ok_result():
    client = FakeMCPClient(execute_result={"status_code": 403, "ok": False, "body": {"error": "forbidden"}})
    entrypoint = DynamicToolEntrypoint("crm.customer.create", client)

    result = await entrypoint(name="ABC Corp")
    parsed = json.loads(result)

    assert parsed["error"] is True
    assert parsed["status_code"] == 403
    assert "MCP Gateway" in parsed["note"]


@pytest.mark.asyncio
async def test_entrypoint_fires_on_event_callbacks():
    events = []

    def on_event(name, payload):
        events.append((name, payload))

    client = FakeMCPClient()
    entrypoint = DynamicToolEntrypoint("crm.customer.create", client, on_event=on_event)

    await entrypoint(name="ABC Corp")

    event_names = [e[0] for e in events]
    assert event_names == ["tool_call_started", "tool_call_completed"]
