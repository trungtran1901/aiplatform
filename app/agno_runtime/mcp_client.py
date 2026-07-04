"""
MCP Gateway client - SSE transport.

MCP Gateway Core exposes a real MCP server over SSE (see its
`mcp_server/` package, served on port 8100 at `GET /sse`). Every enabled
capability in the Gateway's registry appears there as a named MCP tool
(`tools/list`), callable via `tools/call`. This is the real Model
Context Protocol (JSON-RPC over SSE), not a REST endpoint - so this
client does not hand-roll HTTP calls; it opens a real MCP client session
using Agno's own `agno.tools.mcp.MCPTools`, which wraps the official
`mcp` SDK's `sse_client`.

AUTH PROPAGATION (unchanged contract): the inbound Authorization /
X-API-Key headers captured in app.core.auth_context are forwarded
verbatim as SSE connection headers. This client never inspects, decodes,
or makes a decision based on those headers - MCP Gateway is the only
thing that authorizes anything. If a tool call is rejected by the
Gateway, the underlying `mcp` SDK surfaces that as a normal tool error
(CallToolResult.isError) which Agno's own MCP entrypoint turns into a
regular tool-result message for the LLM - this client adds no
interpretation on top of that.

One MCPSession is opened per chat turn (not held open across turns),
matching the platform's stateless-runtime design: the tool catalog is
rebuilt from current metadata on every call to `/api/v1/chat`.
"""
from __future__ import annotations

from contextlib import AsyncExitStack

from agno.tools.mcp import MCPTools, SSEClientParams

from app.core.auth_context import get_propagated_auth
from app.core.config import get_settings
from app.core.exceptions import MCPGatewayError
from app.core.logging import get_logger

logger = get_logger(__name__)


class MCPSession:
    """One live SSE connection to MCP Gateway's MCP server, scoped to a
    single chat turn / Agno run.

    Usage:
        async with MCPSession(include_tools=["customer.create", ...]) as session:
            tools = session.tools   # an agno.tools.mcp.MCPTools instance, ready for Agent(tools=[...])
    """

    def __init__(
        self,
        *,
        include_tools: list[str] | None = None,
        url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.url = url or settings.MCP_GATEWAY_SSE_URL
        self.timeout_seconds = timeout_seconds or settings.MCP_GATEWAY_TIMEOUT_SECONDS
        self.include_tools = include_tools
        self._exit_stack: AsyncExitStack | None = None
        self.tools: MCPTools | None = None

    def _build_headers(self) -> dict[str, str]:
        """Builds the SSE connection headers, forwarding inbound
        credentials unchanged - see module docstring."""
        auth = get_propagated_auth()
        return auth.as_forward_headers()

    async def __aenter__(self) -> "MCPSession":
        headers = self._build_headers()
        logger.info(
            "mcp_sse_connect",
            url=self.url,
            include_tools=self.include_tools,
            has_credentials=get_propagated_auth().has_credentials,
        )

        self.tools = MCPTools(
            transport="sse",
            server_params=SSEClientParams(
                url=self.url,
                headers=headers or None,
                timeout=self.timeout_seconds,
            ),
            timeout_seconds=int(self.timeout_seconds),
            include_tools=self.include_tools,
        )

        try:
            await self.tools.__aenter__()
        except Exception as exc:  # noqa: BLE001
            logger.error("mcp_sse_connect_failed", error=str(exc), url=self.url)
            raise MCPGatewayError(f"Failed to connect to MCP Gateway SSE endpoint {self.url}: {exc}") from exc

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.tools is not None:
            try:
                await self.tools.__aexit__(exc_type, exc_val, exc_tb)
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp_sse_disconnect_error", error=str(exc))