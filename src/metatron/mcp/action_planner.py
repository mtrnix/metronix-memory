"""Action planner — LLM selects MCP write tool and prepares arguments.

Given a user request and available write tools from MCP servers,
the planner asks the LLM to pick the best tool, fill arguments,
and generate a human-readable preview for confirmation.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any

import structlog

from metatron.mcp.adapter import classify_tool
from metatron.mcp.client import MCPClient
from metatron.mcp.registry import MCPServerRegistry

logger = structlog.get_logger()

ACTION_PLANNER_PROMPT = """\
You are an action planner for Metatron, an enterprise knowledge system.

The user wants to perform an action. Available write tools from connected MCP servers:

{tools_description}

Analyze the user's request and select the most appropriate tool.

Respond in JSON ONLY (no markdown, no backticks):
{{
    "server": "server_name",
    "tool": "tool_name",
    "arguments": {{ ... tool arguments ... }},
    "description": "Short human-readable description of what will happen",
    "preview": "Detailed preview:\\n- Field: value\\n- Field: value\\n..."
}}

If no suitable tool is available, respond:
{{
    "error": "No suitable tool found for this action",
    "suggestion": "What the user could do instead"
}}

Rules:
- Select exactly ONE tool
- Fill all required arguments from the user's request
- If the user didn't specify a required field, use a sensible default
- description should be 1 sentence
- preview should show all fields that will be set
- For text content, generate well-formatted content based on user's intent\
"""


class ActionPolicy:
    """Controls which actions are allowed. Future: RBAC integration.

    For MVP: all actions require confirmation, all users can execute.
    """

    REQUIRE_CONFIRMATION: bool = True

    @staticmethod
    def is_allowed(user_id: str, tool_name: str) -> bool:
        """Check if user can execute this action. Future: check RBAC."""
        return True

    @staticmethod
    def requires_confirmation(tool_name: str) -> bool:
        """Check if action needs user confirmation."""
        return ActionPolicy.REQUIRE_CONFIRMATION


class ActionPlanner:
    """Uses LLM to select write tool and prepare arguments.

    Flow:
    1. Discover write tools from enabled MCP servers
    2. Format tools for LLM prompt
    3. LLM selects tool + fills arguments
    4. Return structured plan for confirmation
    """

    def __init__(self, registry: MCPServerRegistry | None = None) -> None:
        self._registry = registry or MCPServerRegistry()

    def discover_write_tools(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """Discover write tools from all enabled MCP servers.

        Connects to each server, lists tools, classifies as read/write,
        returns write tools with server context.

        Args:
            workspace_id: Filter servers by workspace.

        Returns:
            List of tool dicts with server, tool, description, inputSchema.
        """
        servers = self._registry.list_enabled(workspace_id)
        if not servers:
            return []

        write_tools: list[dict[str, Any]] = []

        for server in servers:
            # If server has explicit write_tools configured, use those
            if server.write_tools:
                for tool_name in server.write_tools:
                    write_tools.append({
                        "server": server.name,
                        "tool": tool_name,
                        "description": "",
                        "inputSchema": {},
                    })
                continue

            # Otherwise, connect and discover
            try:
                tools = self._list_tools_sync(server)
                for t in tools:
                    if classify_tool(t["name"], t.get("description", "")) == "write":
                        write_tools.append({
                            "server": server.name,
                            "tool": t["name"],
                            "description": t.get("description", ""),
                            "inputSchema": t.get("inputSchema", {}),
                        })
            except Exception as e:
                logger.warning(
                    "action.planner.discover_error",
                    server=server.name,
                    error=str(e),
                )

        logger.info("action.planner.discovered", write_tools=len(write_tools))
        return write_tools

    @staticmethod
    def _list_tools_sync(server_config: Any) -> list[dict[str, Any]]:
        """List tools from an MCP server (sync wrapper, async-safe).

        Safe to call from both sync and async contexts.
        """
        async def _list() -> list[dict[str, Any]]:
            async with MCPClient(server_config) as client:
                return await client.list_tools()

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _list()).result()
        except RuntimeError:
            return asyncio.run(_list())

    @staticmethod
    def _format_tools_description(tools: list[dict[str, Any]]) -> str:
        """Format tools for the LLM prompt."""
        lines = []
        for t in tools:
            schema = json.dumps(t.get("inputSchema", {}), indent=2)
            lines.append(
                f"Server: {t['server']}\n"
                f"Tool: {t['tool']}\n"
                f"Description: {t['description']}\n"
                f"Input schema:\n{schema}"
            )
        return "\n\n---\n\n".join(lines)

    def plan(self, user_request: str, write_tools: list[dict[str, Any]],
             context: str = "") -> dict[str, Any]:
        """Ask LLM to select a tool and prepare arguments.

        Args:
            user_request: The user's action request text.
            write_tools: Available write tools (from discover_write_tools).
            context: Optional knowledge base context for richer planning.

        Returns:
            Dict with keys: server, tool, arguments, description, preview.
            Or dict with keys: error, suggestion.
        """
        from metatron.llm import chat_completion

        if not write_tools:
            return {
                "error": "No write tools available",
                "suggestion": "Connect MCP servers with write capabilities using /mcp add",
            }

        tools_desc = self._format_tools_description(write_tools)
        prompt = ACTION_PLANNER_PROMPT.format(tools_description=tools_desc)

        user_message = user_request
        if context:
            user_message = (
                f"Context from knowledge base:\n{context}\n\n"
                f"User request: {user_request}"
            )

        try:
            response = chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                timeout=30,
            )
        except Exception as e:
            logger.error("action.planner.llm_error", error=str(e))
            return {
                "error": "Action planning failed. Try again later.",
                "suggestion": "Try rephrasing your request",
            }

        try:
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except (json.JSONDecodeError, IndexError) as e:
            logger.error(
                "action.planner.parse_error",
                error=str(e),
                response=response[:200],
            )
            return {
                "error": "Failed to plan action",
                "suggestion": "Try rephrasing your request",
            }
