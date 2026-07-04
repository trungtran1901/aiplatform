"""
MCP Tool Adapter - SSE transport.

Flow (per spec):
    Load Capabilities -> Build Tool Catalog -> Inject Tools Into Agent

With a real MCP-over-SSE Gateway, "building the tool catalog" means
opening an MCP client session and asking the Gateway's `tools/list` for
its full tool set, then filtering down to exactly the effective
capability codes computed by capability_service (intersection across
AgentOS/Team/Agent). Agno's own `agno.tools.mcp.MCPTools` does the
filtering via `include_tools`, and turns each remaining MCP tool
definition (name + description + JSON Schema) into a real
`agno.tools.function.Function` automatically - so no manual Function
construction is needed here.

No tool is ever hardcoded: the effective capability list comes from the
database (capability_service), and the schema for each one comes live
from the Gateway's `tools/list` response.
"""
from __future__ import annotations

from app.agno_runtime.mcp_client import MCPSession
from app.core.logging import get_logger

logger = get_logger(__name__)


class ToolCatalogBuilder:
    """Opens one MCP session scoped to the effective capability set for
    a single chat turn, ready to be passed into Agno's `tools=[...]`.

    Usage:
        async with ToolCatalogBuilder().build(effective_capabilities) as mcp_session:
            tools = [mcp_session.tools]
            agent = Agent(..., tools=tools)
            await agent.arun(message)
    """

    def build(self, capability_codes: list[str]) -> MCPSession:
        """Load Capabilities -> Build Tool Catalog step.

        Returns an (unopened) MCPSession context manager scoped to
        exactly `capability_codes`. Capability codes are matched against
        MCP tool names exposed by the Gateway's `tools/list` - the
        Gateway is expected to name each tool identically to its
        capability code (e.g. "customer.create"), per its own
        capability-registry contract.

        SECURITY NOTE: agno.tools.mcp.MCPTools treats `include_tools=None`
        as "no filter - expose every tool the Gateway has", and
        `include_tools=[]` as "expose nothing" (no tool name can match an
        empty list). When capability_service's intersection legitimately
        resolves to zero effective capabilities, we MUST pass that
        through as an empty list, not coerce it to None - doing the
        latter would silently grant full, unfiltered access to every
        capability on the Gateway instead of none. `None` is only used
        when the caller explicitly didn't ask for any filtering at all
        (not currently exercised by chat_service, which always calls
        this with a real, possibly-empty, capability_codes list).
        """
        logger.info("tool_catalog_requested", capability_codes=capability_codes)
        return MCPSession(include_tools=capability_codes)