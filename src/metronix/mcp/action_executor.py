"""Action executor — runs confirmed MCP write actions.

Takes a PendingAction (already confirmed by the user), connects to
the MCP server, calls the write tool, and returns the result.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

import structlog

from metronix.mcp.action_store import PendingAction
from metronix.mcp.client import MCPClient
from metronix.mcp.registry import MCPServerRegistry

logger = structlog.get_logger()


class ActionExecutor:
    """Executes confirmed write actions via MCP.

    Connects to the target MCP server, calls the tool with
    prepared arguments, and returns a success/error result.
    """

    def __init__(self, registry: MCPServerRegistry | None = None) -> None:
        self._registry = registry or MCPServerRegistry()

    def execute(self, action: PendingAction) -> dict[str, Any]:
        """Execute a confirmed action (sync wrapper, async-safe).

        Safe to call from both sync and async contexts. When called
        from a thread inside an async loop (e.g. asyncio.to_thread),
        runs the coroutine in a fresh thread to avoid deadlock.

        Args:
            action: The confirmed PendingAction to execute.

        Returns:
            Dict with "success" bool and "result" or "error" string.
        """
        try:
            asyncio.get_running_loop()
            # Inside an async context — run in a separate thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, self.execute_async(action)).result()
        except RuntimeError:
            # No running loop — safe to use asyncio.run directly
            return asyncio.run(self.execute_async(action))

    async def execute_async(self, action: PendingAction) -> dict[str, Any]:
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
                    action.tool_name,
                    action.arguments,
                )

            texts = [block.get("text", "") for block in result_blocks if block.get("text")]
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
            return {
                "success": False,
                "error": "Action execution failed. Check logs for details.",
            }
