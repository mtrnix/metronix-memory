from __future__ import annotations

from typing import Any

from metronix.core.config import get_settings
from metronix.export.deps import build_export_service
from metronix.export.models import ExportScope
from metronix.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metronix.mcp.server import mcp


@mcp.tool(
    description=(
        "Export ALL data for a workspace (or all workspaces) to a downloadable ZIP: "
        "one Markdown file per agent's memory (including unregistered agents) plus "
        "every ingested document in original whole form. Runs in the background.\n\n"
        "**Parameters:**\n"
        "- workspace_id: Target workspace (required unless all_workspaces=true)\n"
        "- all_workspaces: Export every workspace in one archive (default false)\n\n"
        "**Returns:** export_id and status. Poll metronix_export_status for the "
        "download_url once status is 'ready'."
    ),
)
async def metronix_export_data(
    workspace_id: str | None = None,
    all_workspaces: bool = False,
) -> dict[str, Any]:
    """Start a background data export. No silent 'default' workspace fallback."""
    try:
        if not all_workspaces and not workspace_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=(
                        "metronix_export_data: workspace_id is required unless all_workspaces=true"
                    ),
                    hint="Pass an explicit workspace_id, or set all_workspaces=true",
                ).to_dict(),
            }
        scope = ExportScope(all_workspaces=all_workspaces, workspace_id=workspace_id)
        service = build_export_service(get_settings())
        job = await service.start(scope)
        return {"export_id": job.id, "status": str(job.status)}
    except Exception as exc:  # noqa: BLE001
        return {"error": handle_tool_error("metronix_export_data", exc).to_dict()}


@mcp.tool(
    description=(
        "Check the status of a data export started by metronix_export_data.\n\n"
        "**Parameters:**\n- export_id: The id returned by metronix_export_data\n\n"
        "**Returns:** status (pending|running|ready|failed), counts, size_bytes, and "
        "download_url when ready."
    ),
)
async def metronix_export_status(export_id: str) -> dict[str, Any]:
    """Return current export status, including a one-time download_url when ready."""
    try:
        if not export_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_export_status: export_id is required",
                ).to_dict(),
            }
        service = build_export_service(get_settings())
        result = await service.status(export_id)
        if result is None:
            return {
                "error": MCPError(
                    code=ErrorCode.DOCUMENT_NOT_FOUND,
                    message=f"metronix_export_status: no export with id '{export_id}'",
                ).to_dict(),
            }
        return result
    except Exception as exc:  # noqa: BLE001
        return {"error": handle_tool_error("metronix_export_status", exc).to_dict()}
