"""MCP tool: metronix_source_list — list data-source connections."""

from __future__ import annotations

from typing import Any

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp


@mcp.tool(
    description=(
        "List configured data sources (connections) for a workspace.\n\n"
        "**Parameters:**\n"
        "- workspace_id: Target workspace (optional; uses the server default)\n\n"
        "**Returns:** sources[] with masked secrets (last 4 chars shown), plus "
        "status, enabled, error_message, last_synced_at, sync_cron, next_run_at. "
        "Poll this after metronix_source_sync to observe sync status."
    ),
)
async def metronix_source_list(workspace_id: str | None = None) -> dict[str, Any]:
    """List data-source connections for the workspace."""
    try:
        from metronix.mcp.tools._source_deps import resolve
        from metronix.mcp.tools.models import SourceDTO, SourceListResponse

        ws_id, store, fernet_key = resolve(workspace_id)
        conns = await store.list_connections(ws_id, fernet_key)
        sources = [SourceDTO(**c) for c in conns]
        return SourceListResponse(sources=sources, count=len(sources)).model_dump()
    except Exception as e:
        return {"error": handle_tool_error("metronix_source_list", e).to_dict()}
