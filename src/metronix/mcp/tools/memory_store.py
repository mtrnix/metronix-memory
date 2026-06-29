"""MCP tool: metronix_memory_store — persist an agent memory record."""

from __future__ import annotations

from typing import Any

import structlog

from metronix.core.models import MemoryKind, MemoryRecord, MemoryScope
from metronix.core.utils import is_valid_agent_id
from metronix.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools import _memory_deps
from metronix.mcp.tools._memory_utils import scope_from_str, validate_kind
from metronix.mcp.tools.models import MemoryStoreResponse

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
        "- session_id: Required when scope=session\n"
        "- kind: fact | preference | pinned (default fact)\n\n"
        "**Returns:** ``id``, ``content_hash``, ``deduped`` flag."
    ),
)
async def metronix_memory_store(
    content: str,
    agent_id: str,
    workspace_id: str | None = None,
    scope: str = "per_agent",
    tags: list[str] | None = None,
    importance_score: float = 0.5,
    source_type: str = "",
    session_id: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Persist a single memory record — PG+Qdrant+Neo4j, or Redis for session scope."""
    try:
        if not content or not content.strip():
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_memory_store: content is required",
                ).to_dict(),
            }
        if not agent_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_memory_store: agent_id is required",
                ).to_dict(),
            }
        if not is_valid_agent_id(agent_id):
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_memory_store: agent_id must be 1-64 chars of A-Za-z0-9._-",
                ).to_dict(),
            }

        try:
            scope_enum = scope_from_str(scope)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metronix_memory_store: {exc}",
                ).to_dict(),
            }

        try:
            validated_kind = validate_kind(kind)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metronix_memory_store: {exc}",
                ).to_dict(),
            }

        if scope_enum == MemoryScope.SESSION and not session_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=("metronix_memory_store: session_id is required when scope=session"),
                ).to_dict(),
            }

        from metronix.mcp.config import resolve_workspace_id

        ws_id = resolve_workspace_id(workspace_id)
        record = MemoryRecord(
            workspace_id=ws_id,
            agent_id=agent_id,
            scope=scope_enum,
            kind=validated_kind or MemoryKind.FACT,
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
            "metronix_memory_store.done",
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
        error = handle_tool_error("metronix_memory_store", exc)
        return {"error": error.to_dict()}
