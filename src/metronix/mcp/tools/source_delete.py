"""MCP tool: metronix_source_delete — delete a data-source connection."""

from __future__ import annotations

from typing import Any

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp


@mcp.tool(
    description=(
        "Delete a data source (connection) and its encrypted credentials.\n\n"
        "**Parameters:**\n"
        "- connection_id: the source to delete (required)\n"
        "- workspace_id: target workspace (optional, defaults to 'default')\n\n"
        "**Returns:** {success, connection_id}. Already-ingested documents are "
        "not removed by this call."
    ),
)
async def metronix_source_delete(
    connection_id: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Delete a data-source connection."""
    try:
        from metronix.mcp.tools._source_deps import resolve

        ws_id, store, fernet_key = resolve(workspace_id)
        existing = await store.get_connection(connection_id, fernet_key)
        if existing is None or existing["workspace_id"] != ws_id:
            raise ValueError("Connection not found")

        deleted = await store.delete_connection(connection_id)
        return {"success": bool(deleted), "connection_id": connection_id}
    except Exception as e:
        return {"error": handle_tool_error("metronix_source_delete", e).to_dict()}
