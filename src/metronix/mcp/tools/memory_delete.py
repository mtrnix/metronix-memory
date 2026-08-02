"""MCP tool: metronix_memory_delete — delete a persistent memory record."""

from __future__ import annotations

from typing import Any

import structlog

from metronix.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools import _memory_deps
from metronix.mcp.tools._agent_access import require_agent_access
from metronix.mcp.tools.models import MemoryDeleteResponse

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "Delete a persistent memory record by id (PG + Qdrant + Neo4j).\n\n"
        "**Parameters:**\n"
        "- record_id: Record id to delete (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n\n"
        "Note: session-scoped records are managed via the session lifecycle API,\n"
        "not this tool. Only PG-backed records are affected."
    ),
)
async def metronix_memory_delete(
    record_id: str,
    agent_id: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Delete a persistent memory record by id."""
    try:
        if not record_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_memory_delete: record_id is required",
                ).to_dict(),
            }

        from metronix.core.utils import is_valid_agent_id

        if not agent_id or not is_valid_agent_id(agent_id):
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_memory_delete: agent_id must be 1-64 chars of A-Za-z0-9._-",
                ).to_dict(),
            }

        from metronix.mcp.config import resolve_workspace_id

        ws_id = resolve_workspace_id(workspace_id)
        await require_agent_access(ws_id, agent_id, "write")
        service = await _memory_deps.build_memory_service_for_workspace(ws_id)
        deleted = await service.delete(ws_id, record_id, agent_id=agent_id)

        if not deleted:
            return {
                "error": MCPError(
                    code=ErrorCode.DOCUMENT_NOT_FOUND,
                    message=f"Memory record not found: {record_id}",
                    hint="Check record_id or workspace_id; session records are managed elsewhere",
                ).to_dict(),
            }

        logger.info(
            "metronix_memory_delete.done",
            workspace_id=ws_id,
            record_id=record_id,
        )
        return MemoryDeleteResponse(success=True, found=True).model_dump()

    except Exception as exc:  # noqa: BLE001 — wrapped as MCPError
        error = handle_tool_error("metronix_memory_delete", exc)
        return {"error": error.to_dict()}
