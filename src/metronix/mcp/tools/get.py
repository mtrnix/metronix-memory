"""MCP tool: metronix_get — retrieve document by label."""

from __future__ import annotations

from typing import Any

from metronix.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools.models import DocumentResponse


@mcp.tool(
    description=(
        "Retrieve a specific document by its unique label.\n\n"
        "**Parameters:**\n"
        "- doc_label: Unique document label (e.g., 'MTRNIX-42', 'DOC-100')\n"
        "- workspace_id: Workspace containing the document (optional)\n\n"
        "**Returns:** Full document content with metadata."
    ),
)
async def metronix_get(
    doc_label: str,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve a specific document by label."""
    try:
        from metronix.storage.qdrant import get_hybrid_store

        if not doc_label:
            raise ValueError("doc_label is required")

        from metronix.mcp.config import resolve_workspace_id

        store = get_hybrid_store(resolve_workspace_id(workspace_id))
        results = store.search_by_doc_labels([doc_label], limit=1)

        if not results:
            return {
                "error": MCPError(
                    code=ErrorCode.DOCUMENT_NOT_FOUND,
                    message=f"Document not found: {doc_label}",
                    hint="Check the document label or use search to find documents",
                ).to_dict()
            }

        doc = results[0]
        content = doc.get("data") or doc.get("memory") or doc.get("content", "")
        return DocumentResponse(
            doc_label=doc.get("doc_label", doc_label),
            title=doc.get("title", ""),
            content=content,
            source_type=doc.get("source_type") or doc.get("type", "unknown"),
            timestamp=doc.get("date") or doc.get("timestamp"),
            metadata=doc.get("metadata", {}),
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metronix_get", e)
        return {"error": error.to_dict()}
