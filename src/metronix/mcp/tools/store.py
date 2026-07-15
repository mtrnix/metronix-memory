"""MCP tool: metronix_store — store a document."""

from __future__ import annotations

from typing import Any

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools.models import StoreResponse


@mcp.tool(
    description=(
        "Store a new document or memory in the knowledge base.\n\n"
        "**Parameters:**\n"
        "- content: Document content (required)\n"
        "- title: Optional document title\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- doc_label: Optional unique identifier (auto-generated if not provided)\n"
        "- metadata: Additional key-value metadata\n\n"
        "**Returns:** Success status, document label, and chunk count."
    ),
)
async def metronix_store(
    content: str,
    title: str | None = None,
    workspace_id: str | None = None,
    doc_label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a new document in the knowledge base."""
    try:
        if not content or not content.strip():
            raise ValueError("content is required")

        from metronix.ingestion.store import store_document
        from metronix.mcp.config import resolve_workspace_id
        from metronix.mcp.tools._source_deps import get_store

        ws_id = resolve_workspace_id(workspace_id)
        # Reuse the process-cached store (shared with the source tools) rather
        # than spinning up a fresh engine/pool per call; do NOT close it.
        store = get_store()

        success, resolved_doc_label, chunks_stored = await store_document(
            store,
            workspace_id=ws_id,
            content=content,
            title=title,
            doc_label=doc_label,
            metadata=metadata,
        )

        return StoreResponse(
            success=success,
            doc_label=resolved_doc_label,
            chunks_stored=chunks_stored,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metronix_store", e)
        return {"error": error.to_dict()}
