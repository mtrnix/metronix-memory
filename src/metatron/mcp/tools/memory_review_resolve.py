"""MCP tool: metatron_memory_review_resolve — apply resolution to a review entry.

MTRNIX-314. Soft-transition semantics only:
* ``keep``              -> status=ACTIVE
* ``archive``           -> status=ARCHIVED
* ``merge_into:<id>``   -> status=SUPERSEDED with ``superseded_by=<id>``
* ``discard``           -> status=ARCHIVED (no hard DELETE at MCP layer)

Emits a ``freshness_review_resolved`` MachineEvent for audit and fires the
``FRESHNESS_REVIEW_RESOLVED`` EventBus event when one is wired into the
MemoryService.
"""

from __future__ import annotations

from typing import Any

import structlog

from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools.models import MemoryReviewResolveResponse

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "Apply a resolution to a memory review-queue entry.\n\n"
        "**Parameters:**\n"
        "- review_id: Review entry id (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- action: keep | archive | merge_into:<record_id> | discard "
        "(required)\n"
        "- notes: Free-form audit note, capped at 1024 chars (optional)\n\n"
        "**Returns:** review_id, target_id, action, old_status, new_status, "
        "superseded_by?, machine_event_id.\n\n"
        "**Semantics:**\n"
        "- keep: memory record status -> ACTIVE; review entry deleted.\n"
        "- archive: status -> ARCHIVED.\n"
        "- merge_into:<id>: current record status -> SUPERSEDED with "
        "superseded_by=<id>. Content/tag auto-merge is not performed "
        "(future work).\n"
        "- discard: status -> ARCHIVED (soft delete; no hard DELETE at MCP "
        "layer).\n\n"
        "Emits a MachineEvent (event_type=freshness_review_resolved) and "
        "publishes the FRESHNESS_REVIEW_RESOLVED EventBus event when "
        "available."
    ),
)
async def metatron_memory_review_resolve(
    review_id: str,
    action: str,
    workspace_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Resolve a memory review entry via soft status transition."""
    try:
        if not review_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_review_resolve: review_id is required",
                ).to_dict(),
            }
        if not action:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_review_resolve: action is required",
                    hint="One of keep | archive | merge_into:<id> | discard",
                ).to_dict(),
            }

        ws_id = workspace_id or "default"
        service = await _memory_deps.build_memory_service_for_workspace(ws_id)

        try:
            resolution = await service.resolve_review(
                ws_id,
                review_id=review_id,
                action=action,
                notes=notes,
            )
        except ValueError as exc:
            # Malformed action / unknown action / missing merge target -> 400.
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metatron_memory_review_resolve: {exc}",
                ).to_dict(),
            }

        logger.info(
            "metatron_memory_review_resolve.done",
            workspace_id=ws_id,
            review_id=resolution.review_id,
            target_id=resolution.target_id,
            action=resolution.action,
            new_status=resolution.new_status,
        )
        return MemoryReviewResolveResponse(
            success=True,
            review_id=resolution.review_id,
            target_id=resolution.target_id,
            action=resolution.action,
            old_status=resolution.old_status,
            new_status=resolution.new_status,
            superseded_by=resolution.superseded_by,
            machine_event_id=resolution.machine_event_id,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — converted to structured MCPError
        error = handle_tool_error("metatron_memory_review_resolve", exc)
        return {"error": error.to_dict()}
