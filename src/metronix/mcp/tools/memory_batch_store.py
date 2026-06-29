"""MCP tool: metronix_memory_batch_store — persist multiple agent memory records."""

from __future__ import annotations

from typing import Any

import structlog

from metronix.core.models import MemoryRecord, MemoryScope
from metronix.core.utils import is_valid_agent_id
from metronix.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools import _memory_deps
from metronix.mcp.tools._memory_utils import scope_from_str
from metronix.mcp.tools.models import MemoryBatchStoreResponse, MemoryBatchStoreResult

logger = structlog.get_logger(__name__)

_MAX_BATCH_SIZE = 100


@mcp.tool(
    description=(
        "Store multiple agent memory records in one call.\n\n"
        "**Parameters:**\n"
        "- records: List of dicts with 'content' (required) and 'tags' (optional)\n"
        "- agent_id: Agent identity (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- scope: global | per_agent | session (default per_agent)\n"
        "- importance_score: 0.0..1.0 (default 0.5)\n"
        "- source_type: Free-form origin label (optional)\n"
        "- session_id: Required when scope=session\n\n"
        "**Returns:** ``stored`` count, ``deduped`` count, ``results`` list."
    ),
)
async def metronix_memory_batch_store(
    records: list[dict[str, Any]],
    agent_id: str,
    workspace_id: str | None = None,
    scope: str = "per_agent",
    importance_score: float = 0.5,
    source_type: str = "",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Persist multiple memory records in a single call."""
    try:
        if not agent_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_memory_batch_store: agent_id is required",
                ).to_dict(),
            }
        if not is_valid_agent_id(agent_id):
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=(
                        "metronix_memory_batch_store: agent_id must be 1-64 chars of A-Za-z0-9._-"
                    ),
                ).to_dict(),
            }

        if not records:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_memory_batch_store: records list is empty",
                ).to_dict(),
            }

        if len(records) > _MAX_BATCH_SIZE:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=(
                        f"metronix_memory_batch_store: too many records"
                        f" ({len(records)}); max {_MAX_BATCH_SIZE}"
                    ),
                ).to_dict(),
            }

        try:
            scope_enum = scope_from_str(scope)
        except ValueError as exc:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"metronix_memory_batch_store: {exc}",
                ).to_dict(),
            }

        if scope_enum == MemoryScope.SESSION and not session_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=(
                        "metronix_memory_batch_store: session_id is required when scope=session"
                    ),
                ).to_dict(),
            }

        from metronix.mcp.config import resolve_workspace_id

        ws_id = resolve_workspace_id(workspace_id)
        service = await _memory_deps.build_memory_service_for_workspace(ws_id)

        results: list[MemoryBatchStoreResult] = []
        stored = 0
        deduped = 0

        for idx, rec in enumerate(records):
            try:
                content = rec.get("content", "")
                if not content or not str(content).strip():
                    results.append(
                        MemoryBatchStoreResult(
                            error=f"record[{idx}]: content is required",
                        )
                    )
                    continue

                tags = rec.get("tags") or []
                record = MemoryRecord(
                    workspace_id=ws_id,
                    agent_id=agent_id,
                    scope=scope_enum,
                    source_type=source_type,
                    content=str(content),
                    tags=list(tags),
                    importance_score=float(importance_score),
                    session_id=session_id,
                )
                new_id = record.id

                if scope_enum == MemoryScope.SESSION:
                    assert session_id is not None  # noqa: S101
                    saved = await service.cache_session(ws_id, session_id, record)
                else:
                    saved = await service.save(ws_id, record)

                is_deduped = saved.id != new_id
                if is_deduped:
                    deduped += 1
                else:
                    stored += 1

                results.append(
                    MemoryBatchStoreResult(
                        id=saved.id,
                        content_hash=saved.content_hash,
                        deduped=is_deduped,
                    )
                )

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "metronix_memory_batch_store.record_error",
                    index=idx,
                    error=str(exc),
                )
                results.append(MemoryBatchStoreResult(error=f"record[{idx}]: {exc}"))

        logger.info(
            "metronix_memory_batch_store.done",
            workspace_id=ws_id,
            agent_id=agent_id,
            scope=scope_enum.value,
            stored=stored,
            deduped=deduped,
        )
        return MemoryBatchStoreResponse(
            stored=stored,
            deduped=deduped,
            results=results,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — wrapped as MCPError
        error = handle_tool_error("metronix_memory_batch_store", exc)
        return {"error": error.to_dict()}
