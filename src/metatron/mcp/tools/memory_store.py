"""MCP tool: metatron_memory_store — persist an agent memory record."""

from __future__ import annotations

from typing import Any

import structlog

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools._memory_utils import scope_from_str
from metatron.mcp.tools.models import MemoryStoreResponse

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "Store an agent memory record.\n\n"
        "**Parameters:**\n"
        "- content: Memory content (required)\n"
        "- agent_id: Agent identity (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- scope: global | per_agent | session (default per_agent)\n"
        "- tags: Tag list (optional)\n"
        "- importance_score: 0.0..1.0 (default 0.5)\n"
        "- source_type: Free-form origin label (optional)\n"
        "- session_id: Required when scope=session\n\n"
        "**Returns:** ``id``, ``content_hash``, ``deduped`` flag."
    ),
)
async def metatron_memory_store(
    content: str,
    agent_id: str,
    workspace_id: str | None = None,
    scope: str = "per_agent",
    tags: list[str] | None = None,
    importance_score: float = 0.5,
    source_type: str = "",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Persist a single memory record — PG+Qdrant+Neo4j, or Redis for session scope."""
    try:
        if not content or not content.strip():
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_store: content is required",
                ).to_dict(),
            }
        if not agent_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_store: agent_id is required",
                ).to_dict(),
            }

        try:
            scope_enum = scope_from_str(scope)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metatron_memory_store: {exc}",
                ).to_dict(),
            }

        if scope_enum == MemoryScope.SESSION and not session_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=("metatron_memory_store: session_id is required when scope=session"),
                ).to_dict(),
            }

        ws_id = workspace_id or "default"
        record = MemoryRecord(
            workspace_id=ws_id,
            agent_id=agent_id,
            scope=scope_enum,
            source_type=source_type,
            content=content,
            tags=list(tags) if tags else [],
            importance_score=float(importance_score),
            session_id=session_id,
        )
        new_id = record.id

        service = await _memory_deps.build_memory_service_for_workspace(ws_id)
        if scope_enum == MemoryScope.SESSION:
            # session_id is non-None here (checked above). ``cast`` via assert to satisfy mypy.
            assert session_id is not None  # noqa: S101 — defensive; validated above
            stored = await service.cache_session(ws_id, session_id, record)
        else:
            stored = await service.save(ws_id, record)

        deduped = stored.id != new_id
        logger.info(
            "metatron_memory_store.done",
            workspace_id=ws_id,
            agent_id=agent_id,
            scope=scope_enum.value,
            deduped=deduped,
        )
        return MemoryStoreResponse(
            id=stored.id,
            content_hash=stored.content_hash,
            deduped=deduped,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — wrapped as MCPError
        error = handle_tool_error("metatron_memory_store", exc)
        return {"error": error.to_dict()}
