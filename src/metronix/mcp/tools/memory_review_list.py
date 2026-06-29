"""MCP tool: metronix_memory_review_list — list pending memory review-queue rows.

MTRNIX-314. Hard-wired to ``target_kind=memory_record``. KB review queue
(``raw_document``) is out of scope for this ticket (Control Center).
"""

from __future__ import annotations

from typing import Any

import structlog

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools import _memory_deps
from metronix.mcp.tools.models import MemoryReviewListResponse, ReviewEntryDTO

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "List pending memory review-queue entries.\n\n"
        "**Parameters:**\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- reason: Filter: possible_duplicate | possible_contradiction | "
        "low_confidence_decision (optional, free-form validated against "
        "known set)\n"
        "- record_id: Filter to review entries for a specific memory record "
        "(optional)\n"
        "- limit: Page size, 1..100 (default 20)\n"
        "- offset: Pagination offset (default 0)\n\n"
        "**Returns:** Paginated list of ReviewEntry rows for "
        "target_kind=memory_record, plus total count."
    ),
)
async def metronix_memory_review_list(
    workspace_id: str | None = None,
    reason: str | None = None,
    record_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated enumeration of ``memory_record`` review entries."""
    try:
        ws_id = workspace_id or "default"
        limit = min(max(1, int(limit)), 100)
        offset = max(0, int(offset))

        service = await _memory_deps.build_memory_service_for_workspace(ws_id)
        entries, total = await service.list_review_entries(
            ws_id,
            record_id=record_id,
            reason=reason,
            limit=limit,
            offset=offset,
        )

        dtos = [
            ReviewEntryDTO(
                id=e.id,
                workspace_id=e.workspace_id,
                target_id=e.target_id,
                target_kind=e.target_kind,
                reason=e.reason,
                related_record_id=e.related_record_id,
                content=e.content,
                confidence=e.confidence,
                created_at=e.created_at,
            )
            for e in entries
        ]

        logger.info(
            "metronix_memory_review_list.done",
            workspace_id=ws_id,
            count=len(dtos),
            total=total,
        )
        return MemoryReviewListResponse(
            entries=dtos,
            count=len(dtos),
            total=total,
            limit=limit,
            offset=offset,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — converted to structured MCPError
        error = handle_tool_error("metronix_memory_review_list", exc)
        return {"error": error.to_dict()}
