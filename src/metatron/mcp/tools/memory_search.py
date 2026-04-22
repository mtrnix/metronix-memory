"""MCP tool: metatron_memory_search — hybrid agent memory search."""

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
from metatron.mcp.tools.models import (
    MemoryRecordDTO,
    MemorySearchToolItem,
    MemorySearchToolResponse,
)

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "Search agent memory via hybrid Qdrant + Neo4j + Redis-session blend.\n\n"
        "**Parameters:**\n"
        "- query: Natural language query (required)\n"
        "- agent_id: Agent identity (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- scope: global | per_agent | session (optional)\n"
        "- tags: Filter by tag list (optional)\n"
        "- session_id: Session id for session-boost leg (optional)\n"
        "- top_k: Results to return (1..50, default 5)\n"
        "- status: Lifecycle statuses to include (list of strings). "
        "Default ``['active']``. Pass ``['all']`` to disable filtering. "
        "Valid values: active, candidate, stale, superseded, archived, "
        "conflicted, review_needed, all.\n\n"
        "**Returns:** Ranked list of memory records with dense/graph/session signals."
    ),
)
async def metatron_memory_search(
    query: str,
    agent_id: str,
    workspace_id: str | None = None,
    scope: str | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
    top_k: int = 5,
    status: list[str] | None = None,
) -> dict[str, Any]:
    """Hybrid search over agent memory records."""
    try:
        if not query or not query.strip():
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_search: query is required",
                    hint="Provide a non-empty natural-language query",
                ).to_dict(),
            }
        if not agent_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_search: agent_id is required",
                    hint="Pass the agent identifier used when storing records",
                ).to_dict(),
            }

        try:
            scope_enum = scope_from_str_optional(scope)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metatron_memory_search: {exc}",
                ).to_dict(),
            }

        try:
            status_filter = parse_status_filter(status)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metatron_memory_search: {exc}",
                ).to_dict(),
            }

        ws_id = workspace_id or "default"
        top_k = min(max(1, int(top_k)), 50)

        service = await _memory_deps.build_memory_service_for_workspace(ws_id)
        results = await service.search(
            ws_id,
            query,
            agent_id=agent_id,
            scope=scope_enum,
            tags=tags,
            session_id=session_id,
            top_k=top_k,
            status_filter=status_filter,
        )

        items: list[MemorySearchToolItem] = []
        for r in results:
            rec = r.record
            items.append(
                MemorySearchToolItem(
                    record=MemoryRecordDTO(
                        id=rec.id,
                        workspace_id=rec.workspace_id,
                        agent_id=rec.agent_id,
                        scope=rec.scope.value,
                        source_type=rec.source_type,
                        content=rec.content,
                        tags=list(rec.tags),
                        importance_score=rec.importance_score,
                        ttl_expires_at=rec.ttl_expires_at,
                        content_hash=rec.content_hash,
                        created_at=rec.created_at,
                        session_id=rec.session_id,
                        metadata=dict(rec.metadata),
                        status=rec.status.value,
                    ),
                    score=r.score,
                    dense_score=r.dense_score,
                    graph_score=r.graph_score,
                    # ``sparse_score`` is a reserved field on MemorySearchResult
                    # (see ``memory/.claude/CLAUDE.md``). Currently always 0.0
                    # because Qdrant fuses dense+sparse server-side via RRF.
                    # Surfaced here as ``session_boost`` for forward-compat when
                    # a client-side session-boost signal lands.
                    session_boost=r.sparse_score,
                    rank=r.rank,
                )
            )

        logger.info(
            "metatron_memory_search.done",
            workspace_id=ws_id,
            agent_id=agent_id,
            count=len(items),
        )
        return MemorySearchToolResponse(results=items, count=len(items)).model_dump()

    except Exception as exc:  # noqa: BLE001 — converted to structured MCPError
        error = handle_tool_error("metatron_memory_search", exc)
        return {"error": error.to_dict()}
