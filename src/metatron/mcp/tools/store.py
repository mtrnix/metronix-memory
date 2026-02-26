"""MCP tool: metatron_store — store a document."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from metatron.mcp.errors import handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools.models import StoreResponse


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
async def metatron_store(
    content: str,
    title: Optional[str] = None,
    workspace_id: Optional[str] = None,
    doc_label: Optional[str] = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a new document in the knowledge base."""
    try:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        if not content:
            raise ValueError("content is required")

        if not doc_label:
            doc_label = f"MEM-{uuid.uuid4().hex[:8].upper()}"

        doc = Document(
            title=title or doc_label,
            content=content,
            source_type="memory",
            source_id=doc_label,
            workspace_id=workspace_id or "default",
            metadata=metadata or {},
        )

        # ingest_documents returns SyncResult (not .success / .new_chunks)
        result = await asyncio.to_thread(
            ingest_documents,
            [doc],
            workspace_id or "default",
            connector_type="memory",
            incremental=False,
        )

        return StoreResponse(
            success=len(result.errors) == 0,
            doc_label=doc_label,
            chunks_stored=result.documents_new,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metatron_store", e)
        return {"error": error.to_dict()}
