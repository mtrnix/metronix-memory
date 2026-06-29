"""MCP tool: metronix_sync — trigger document sync from MCP sources."""

from __future__ import annotations

from typing import Any

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools.models import SyncResponse, SyncSourceResult


@mcp.tool(
    description=(
        "Trigger document sync from configured MCP sources.\n\n"
        "**Parameters:**\n"
        "- source: Specific MCP server name to sync (optional, syncs all)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- force_full: Force full sync, ignoring hash-based change detection\n\n"
        "**Returns:** Success status, sources synced count, and per-source details."
    ),
)
async def metronix_sync(
    source: str | None = None,
    workspace_id: str | None = None,
    force_full: bool = False,
) -> dict[str, Any]:
    """Trigger document sync from configured MCP sources."""
    try:
        from metronix.mcp.sync import MCPSyncManager

        ws_id = workspace_id or "default"
        sync_manager = MCPSyncManager()

        details: list[SyncSourceResult] = []
        success = True

        if source:
            from metronix.mcp.registry import MCPServerRegistry

            registry = MCPServerRegistry()
            server_config = None
            for cfg in registry.list_enabled(ws_id):
                if cfg.name == source:
                    server_config = cfg
                    break

            if not server_config:
                return {
                    "success": False,
                    "sources_synced": 0,
                    "details": [
                        {
                            "source": source,
                            "success": False,
                            "errors": [f"Server not found or not enabled: {source}"],
                        }
                    ],
                }

            result = await sync_manager.sync_server(server_config, ws_id, force_full)
            details.append(
                SyncSourceResult(
                    source=source,
                    success=len(result.errors) == 0,
                    documents_fetched=result.documents_fetched,
                    documents_ingested=result.documents_new + result.documents_updated,
                    documents_skipped=result.documents_skipped,
                    errors=result.errors,
                )
            )
            success = success and len(result.errors) == 0
        else:
            results = await sync_manager.sync_all(ws_id, force_full)
            for server_name, result in results:
                details.append(
                    SyncSourceResult(
                        source=server_name,
                        success=len(result.errors) == 0,
                        documents_fetched=result.documents_fetched,
                        documents_ingested=result.documents_new + result.documents_updated,
                        documents_skipped=result.documents_skipped,
                        errors=result.errors,
                    )
                )
                success = success and len(result.errors) == 0

        return SyncResponse(
            success=success,
            sources_synced=len(details),
            details=[d.model_dump() for d in details],
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metronix_sync", e)
        return {"error": error.to_dict()}
