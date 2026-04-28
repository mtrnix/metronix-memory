"""MCP tool: metatron_memory_get_context — assemble agent memory context for LLM injection."""

from __future__ import annotations

from typing import Any

import structlog

from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools.models import MemoryContextResponse

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "Assemble agent memory context for injection into LLM system prompt.\n\n"
        "**Parameters:**\n"
        "- agent_id: Agent identity (required)\n"
        "- workspace_id: Target workspace (required)\n"
        "- query: User message to find relevant memories (required)\n"
        "- memory_top_k: Number of fact memories to retrieve (default 10)\n\n"
        "**Returns:** ``system_prompt`` with XML-delimited sections "
        "(``<preferences>`` and ``<relevant_memories>``), "
        "``preferences_count``, ``memories_count``.\n\n"
        "Hermes and other MCP clients should call this before each LLM turn "
        "and prepend the ``system_prompt`` to their messages."
    ),
)
async def metatron_memory_get_context(
    agent_id: str,
    workspace_id: str,
    query: str,
    memory_top_k: int = 10,
) -> dict[str, Any]:
    """Assemble structured system prompt with memory context."""
    try:
        if not agent_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_get_context: agent_id is required",
                ).to_dict(),
            }
        if not workspace_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_get_context: workspace_id is required",
                ).to_dict(),
            }
        if not query or not query.strip():
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_get_context: query is required",
                ).to_dict(),
            }

        from metatron.core.config import get_settings

        settings = get_settings()

        # Early return when feature flag is off — byte-identical to pre-MTRNIX-275.
        if not settings.memory_injection_enabled:
            return MemoryContextResponse(
                system_prompt="",
                preferences_count=0,
                memories_count=0,
            ).model_dump()

        # Import here to avoid circular imports at module level.
        from metatron.memory.assembler import AgentContextAssembler

        service = await _memory_deps.build_memory_service_for_workspace(workspace_id)

        assembler = AgentContextAssembler(
            memory_service=service,
            memory_search=service._search,  # noqa: SLF001 — access to wired dep
            settings=settings,
        )

        top_k = memory_top_k or settings.memory_injection_facts_top_k
        ctx = await assembler.assemble(
            agent_id=agent_id,
            workspace_id=workspace_id,
            user_message=query,
            memory_top_k=top_k,
        )

        return MemoryContextResponse(
            system_prompt=ctx.system_prompt,
            preferences_count=ctx.preferences_count,
            memories_count=ctx.memories_count,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — wrapped as MCPError
        error = handle_tool_error("metatron_memory_get_context", exc)
        return {"error": error.to_dict()}
