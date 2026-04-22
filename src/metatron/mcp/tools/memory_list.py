"""MCP tool: metatron_memory_list — list agent memory records with pagination."""

from __future__ import annotations

from typing import Any

import structlog

from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools._memory_utils import (
    parse_status_filter,
    scope_from_str_optional,
)
from metatron.mcp.tools.models import MemoryListResponse, MemoryRecordDTO

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "List all memory records for an agent with pagination.\n\n"
        "**Parameters:**\n"
        "- agent_id: Agent identity (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- scope: global | per_agent | session (optional filter)\n"
        "- tags: Filter by tag list — record must have at least one matching tag (optional)\n"
        "- limit: Page size, 1..100 (default 20)\n"
        "- offset: Number of records to skip (default 0)\n"
        "- status: Lifecycle statuses to include (list of strings). "
        "Default ``['active']``. Pass ``['all']`` to disable filtering. "
        "Valid values: active, candidate, stale, superseded, archived, "
        "conflicted, review_needed, all.\n\n"
        "**Returns:** Paginated list of memory records with total count."
    ),
)
async def metatron_memory_list(
    agent_id: str,
    workspace_id: str | None = None,
    scope: str | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    status: list[str] | None = None,
) -> dict[str, Any]:
    """List agent memory records with pagination."""
    try:
        if not agent_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_list: agent_id is required",
                    hint="Pass the agent identifier used when storing records",
                ).to_dict(),
            }

        try:
            scope_enum = scope_from_str_optional(scope)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metatron_memory_list: {exc}",
                ).to_dict(),
            }

        try:
            status_filter = parse_status_filter(status)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metatron_memory_list: {exc}",
                ).to_dict(),
            }

        ws_id = workspace_id or "default"
        limit = min(max(1, int(limit)), 100)
        offset = max(0, int(offset))

        service = await _memory_deps.build_memory_service_for_workspace(ws_id)

        records = await service.pg_store.list_records(
            ws_id,
            agent_id=agent_id,
            scope=scope_enum,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        total = await service.pg_store.count_records(
            ws_id,
            agent_id=agent_id,
            scope=scope_enum,
            status=status_filter,
        )

        # Post-filter by tags (intersection — record must have at least one matching tag)
        if tags:
            tag_set = set(tags)
            records = [r for r in records if tag_set & set(r.tags)]

        dto_list = [
            MemoryRecordDTO(
                id=r.id,
                workspace_id=r.workspace_id,
                agent_id=r.agent_id,
                scope=r.scope.value,
                source_type=r.source_type,
                content=r.content,
                tags=list(r.tags),
                importance_score=r.importance_score,
                content_hash=r.content_hash,
                created_at=r.created_at,
                session_id=r.session_id,
                metadata=dict(r.metadata) if r.metadata else {},
                status=r.status.value,
            )
            for r in records
        ]

        logger.info(
            "metatron_memory_list.done",
            workspace_id=ws_id,
            agent_id=agent_id,
            count=len(dto_list),
            total=total,
        )
        return MemoryListResponse(
            records=dto_list,
            count=len(dto_list),
            total=total,
            limit=limit,
            offset=offset,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — converted to structured MCPError
        error = handle_tool_error("metatron_memory_list", exc)
        return {"error": error.to_dict()}
