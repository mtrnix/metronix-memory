"""MCP tool: metatron_memory_delete — delete a persistent memory record."""

from __future__ import annotations

from typing import Any

import structlog

from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools.models import MemoryDeleteResponse

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
async def metatron_memory_delete(
    record_id: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Delete a persistent memory record by id."""
    try:
        if not record_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_delete: record_id is required",
                ).to_dict(),
            }

        ws_id = workspace_id or "default"
        service = await _memory_deps.build_memory_service_for_workspace(ws_id)
        deleted = await service.delete(ws_id, record_id)

        if not deleted:
            return {
                "error": MCPError(
                    code=ErrorCode.DOCUMENT_NOT_FOUND,
                    message=f"Memory record not found: {record_id}",
                    hint="Check record_id or workspace_id; session records are managed elsewhere",
                ).to_dict(),
            }

        logger.info(
            "metatron_memory_delete.done",
            workspace_id=ws_id,
            record_id=record_id,
        )
        return MemoryDeleteResponse(success=True, found=True).model_dump()

    except Exception as exc:  # noqa: BLE001 — wrapped as MCPError
        error = handle_tool_error("metatron_memory_delete", exc)
        return {"error": error.to_dict()}
