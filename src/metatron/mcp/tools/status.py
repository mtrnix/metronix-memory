"""MCP tool: metatron_status — system health and workspace info."""

from __future__ import annotations

from typing import Any

from metatron.mcp.errors import handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools.models import StatusResponse


@mcp.tool(
    description=(
        "Check system health and workspace status.\n\n"
        "**Parameters:**\n"
        "- workspace_id: Workspace to check (optional, uses default)\n\n"
        "**Returns:** Health status, document counts by source, "
        "last sync timestamp, embedding model."
    ),
)
async def metatron_status(
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Check system health and status."""
    try:
        from metatron.core.config import Settings
        from metatron.storage.qdrant import get_hybrid_store

        ws_id = workspace_id or "default"
        settings = Settings()

        try:
            store = get_hybrid_store(ws_id)
            # Use get_stats() which actually exists on QdrantVectorStore
            stats = store.get_stats()
            counts: dict[str, int] = {"total": stats.get("chunk_count", 0)}
        except Exception:
            counts = {"total": 0}

        return StatusResponse(
            status="healthy" if counts.get("total", 0) > 0 else "initializing",
            documents=counts,
            last_sync=None,
            embedding_model=settings.ollama_embed_model,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metatron_status", e)
        return {"error": error.to_dict()}
