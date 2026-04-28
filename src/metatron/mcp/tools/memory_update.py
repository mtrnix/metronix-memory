"""MCP tool: metatron_memory_update — update an existing memory record in place."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from metatron.core.models import MemoryKind
from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools.models import MemoryUpdateResponse
from metatron.memory.freshness.producer import enqueue_if_enabled
from metatron.storage.memory_graph import upsert_memory_node

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "Update an existing memory record in place.\n\n"
        "**Parameters:**\n"
        "- record_id: Record id to update (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- content: New content text (optional)\n"
        "- tags: New tag list (optional)\n"
        "- importance_score: New importance 0.0..1.0 (optional)\n"
        "- kind: fact | preference | pinned (optional — promote fact to preference)\n\n"
        "At least one of content/tags/importance_score/kind must be provided.\n"
        "Returns updated record id, content_hash, and list of updated fields."
    ),
)
async def metatron_memory_update(
    record_id: str,
    workspace_id: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    importance_score: float | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Update an existing memory record in place."""
    try:
        if not record_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metatron_memory_update: record_id is required",
                ).to_dict(),
            }

        if content is None and tags is None and importance_score is None and kind is None:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message=(
                        "metatron_memory_update: at least one of "
                        "content, tags, importance_score, or kind must be provided"
                    ),
                ).to_dict(),
            }

        ws_id = workspace_id or "default"

        validated_kind: MemoryKind | None = None
        if kind is not None:
            try:
                validated_kind = MemoryKind(kind.lower())
            except ValueError as exc:
                return {
                    "error": MCPError(
                        code=ErrorCode.INVALID_PARAMS,
                        message=f"metatron_memory_update: {exc}",
                    ).to_dict(),
                }

        service = await _memory_deps.build_memory_service_for_workspace(ws_id)

        updated = await service.pg_store.update(
            ws_id,
            record_id,
            content=content,
            tags=tags,
            importance_score=importance_score,
            kind=validated_kind,
        )

        if updated is None:
            return {
                "error": MCPError(
                    code=ErrorCode.DOCUMENT_NOT_FOUND,
                    message=f"Memory record not found: {record_id}",
                    hint="Check record_id or workspace_id",
                ).to_dict(),
            }

        # Sync to Qdrant (best-effort)
        try:
            if content is not None:
                # Content changed — full re-embed
                await service.qdrant_store.upsert(updated)
            else:
                # Only metadata changed — payload update without re-embedding
                payload: dict[str, Any] = {}
                if tags is not None:
                    payload["tags"] = tags
                if importance_score is not None:
                    payload["importance_score"] = importance_score
                if payload:
                    await service.qdrant_store.update_payload(record_id, payload)
        except Exception:  # noqa: BLE001
            logger.warning(
                "metatron_memory_update.qdrant_sync_failed",
                record_id=record_id,
                exc_info=True,
            )

        # Sync to Neo4j (best-effort)
        try:
            await asyncio.to_thread(upsert_memory_node, updated)
        except Exception:  # noqa: BLE001
            logger.warning(
                "metatron_memory_update.neo4j_sync_failed",
                record_id=record_id,
                exc_info=True,
            )

        updated_fields: list[str] = []
        if content is not None:
            updated_fields.append("content")
        if tags is not None:
            updated_fields.append("tags")
        if importance_score is not None:
            updated_fields.append("importance_score")
        if validated_kind is not None:
            updated_fields.append("kind")

        # Freshness hook — content edits trigger a full re-evaluation, metadata
        # edits only re-tag. Flag-gated so it is a no-op in the default config.
        event_type = "content_changed" if content is not None else "metadata_changed"
        await enqueue_if_enabled(ws_id, record_id, event_type)

        logger.info(
            "metatron_memory_update.done",
            workspace_id=ws_id,
            record_id=record_id,
            updated_fields=updated_fields,
        )
        return MemoryUpdateResponse(
            id=updated.id,
            content_hash=updated.content_hash,
            updated_fields=updated_fields,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — wrapped as MCPError
        error = handle_tool_error("metatron_memory_update", exc)
        return {"error": error.to_dict()}
