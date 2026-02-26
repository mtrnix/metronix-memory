"""MCP tool: metatron_get — retrieve document by label."""

from __future__ import annotations

from typing import Any, Optional

from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools.models import DocumentResponse


@mcp.tool(
    description=(
        "Retrieve a specific document by its unique label.\n\n"
        "**Parameters:**\n"
        "- doc_label: Unique document label (e.g., 'MTRNIX-42', 'DOC-100')\n"
        "- workspace_id: Workspace containing the document (optional)\n\n"
        "**Returns:** Full document content with metadata."
    ),
)
async def metatron_get(
    doc_label: str,
    workspace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve a specific document by label."""
    try:
        from metatron.storage.qdrant import get_hybrid_store

        if not doc_label:
            raise ValueError("doc_label is required")

        store = get_hybrid_store(workspace_id or "default")
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
        return DocumentResponse(
            doc_label=doc.get("doc_label", doc_label),
            title=doc.get("title", ""),
            content=doc.get("content", ""),
            source_type=doc.get("source_type", "unknown"),
            timestamp=doc.get("timestamp"),
            metadata=doc.get("metadata", {}),
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metatron_get", e)
        return {"error": error.to_dict()}
