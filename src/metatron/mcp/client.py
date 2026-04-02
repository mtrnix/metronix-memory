"""MCP client — manages stdio connections to MCP servers.

Handles lifecycle: connect → list tools → call tool → disconnect.
Uses the official `mcp` Python SDK for protocol communication.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from metatron.mcp.config import MCPServerConfig

logger = structlog.get_logger()

# Lazy SDK imports to avoid hard failure if `mcp` is not installed
_ClientSession = None
_StdioServerParameters = None
_stdio_client = None


def _ensure_mcp_sdk() -> None:
    """Import MCP SDK classes on first use."""
    global _ClientSession, _StdioServerParameters, _stdio_client  # noqa: PLW0603
    if _ClientSession is not None:
        return
    try:
        from mcp import ClientSession, StdioServerParameters, stdio_client

        _ClientSession = ClientSession
        _StdioServerParameters = StdioServerParameters
        _stdio_client = stdio_client
    except ImportError as e:
        raise ImportError("MCP SDK not installed. Run: pip install 'mcp>=1.0,<2'") from e


class MCPClient:
    """Manages a stdio connection to one MCP server.

    Usage::

        client = MCPClient(config)
        async with client:
            tools = await client.list_tools()
            result = await client.call_tool("read_file", {"path": "/README.md"})
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: Any = None
        self._context: Any = None
        self._connected = False

    @property
    def connected(self) -> bool:
        """Whether the client has an active session."""
        return self._connected

    async def connect(self) -> None:
        """Start the MCP server subprocess and initialize the session."""
        _ensure_mcp_sdk()

        params = _StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env or None,
        )

        logger.info(
            "mcp.client.connecting",
            server=self.config.name,
            command=self.config.command,
        )

        self._stdio_ctx = _stdio_client(params)
        read_stream, write_stream = await self._stdio_ctx.__aenter__()

        self._session = _ClientSession(read_stream, write_stream)
        self._session_ctx = self._session.__aenter__()
        await self._session_ctx

        await self._session.initialize()
        self._connected = True

        logger.info("mcp.client.connected", server=self.config.name)

    async def disconnect(self) -> None:
        """Close the session and stop the subprocess.

        Disconnect errors (e.g. "cancel scope in different task" from
        MCP SDK + asyncio.run) are logged at debug level since data
        was already fetched successfully.
        """
        if not self._connected:
            return
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
            if hasattr(self, "_stdio_ctx"):
                await self._stdio_ctx.__aexit__(None, None, None)
        except Exception as e:
            logger.debug(
                "mcp.client.disconnect_cleanup",
                server=self.config.name,
                error=str(e),
            )
        finally:
            self._session = None
            self._connected = False
            logger.info("mcp.client.disconnected", server=self.config.name)

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the connected MCP server.

        Returns:
            List of tool descriptors with name, description, inputSchema.
        """
        if not self._connected or not self._session:
            raise RuntimeError("Not connected — call connect() first")

        result = await self._session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": getattr(tool, "description", "") or "",
                    "inputSchema": getattr(tool, "inputSchema", {}) or {},
                }
            )

        logger.info("mcp.client.list_tools", server=self.config.name, count=len(tools))
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> list[dict[str, Any]]:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to invoke.
            arguments: Tool input parameters.
            timeout: Maximum seconds to wait for the result.

        Returns:
            List of content blocks from the tool result.
        """
        if not self._connected or not self._session:
            raise RuntimeError("Not connected — call connect() first")

        logger.info(
            "mcp.client.call_tool",
            server=self.config.name,
            tool=tool_name,
        )

        result = await asyncio.wait_for(
            self._session.call_tool(tool_name, arguments or {}),
            timeout=timeout,
        )

        content_blocks = []
        for block in result.content:
            content_blocks.append(
                {
                    "type": getattr(block, "type", "text"),
                    "text": getattr(block, "text", str(block)),
                }
            )

        logger.info(
            "mcp.client.tool_result",
            server=self.config.name,
            tool=tool_name,
            blocks=len(content_blocks),
        )
        return content_blocks
