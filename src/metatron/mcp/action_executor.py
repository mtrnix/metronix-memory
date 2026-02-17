"""Action executor — runs confirmed MCP write actions.

Takes a PendingAction (already confirmed by the user), connects to
the MCP server, calls the write tool, and returns the result.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from metatron.mcp.action_store import PendingAction
from metatron.mcp.client import MCPClient
from metatron.mcp.registry import MCPServerRegistry

logger = structlog.get_logger()


class ActionExecutor:
    """Executes confirmed write actions via MCP.

    Connects to the target MCP server, calls the tool with
    prepared arguments, and returns a success/error result.
    """

    def __init__(self, registry: MCPServerRegistry | None = None) -> None:
        self._registry = registry or MCPServerRegistry()

    def execute(self, action: PendingAction) -> dict[str, Any]:
        """Execute a confirmed action (sync wrapper).

        Args:
            action: The confirmed PendingAction to execute.

        Returns:
            Dict with "success" bool and "result" or "error" string.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._execute_async(action))
        finally:
            loop.close()

    async def _execute_async(self, action: PendingAction) -> dict[str, Any]:
        """Execute a confirmed action via MCP Client.

        Args:
            action: The confirmed PendingAction.

        Returns:
            Dict with "success" bool and "result" or "error" string.
        """
        config = self._registry.get(action.server_name)
        if not config:
            return {
                "success": False,
                "error": f"Server '{action.server_name}' not found",
            }

        try:
            async with MCPClient(config) as client:
                result_blocks = await client.call_tool(
                    action.tool_name, action.arguments,
                )

            texts = [
                block.get("text", "")
                for block in result_blocks
                if block.get("text")
            ]
            result_text = "\n".join(texts) if texts else "Action completed"

            logger.info(
                "action.executed",
                server=action.server_name,
                tool=action.tool_name,
                user_id=action.user_id,
            )
            return {"success": True, "result": result_text}

        except Exception as e:
            logger.error(
                "action.execute.error",
                server=action.server_name,
                tool=action.tool_name,
                error=str(e),
                exc_info=True,
            )
            return {"success": False, "error": str(e)}
