"""MCP tool: metronix_search — hybrid RAG search."""

from __future__ import annotations

from typing import Any

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools.models import SearchResponse, SearchResultItem


@mcp.tool(
    description=(
        "Search the knowledge base using hybrid RAG "
        "(vector + BM25 + knowledge graph).\n\n"
        "**Parameters:**\n"
        "- query: Natural language question or search term (required)\n"
        "- workspace_id: Specific workspace (optional, uses default)\n"
        "- limit: Results per page (1-100, default 10)\n"
        "- cursor: Pagination cursor from previous response\n"
        "- include_graph: Include knowledge graph context (default false)\n\n"
        "**Returns:** List of relevant documents with title, content, source, and score."
    ),
)
async def metronix_search(
    query: str,
    workspace_id: str | None = None,
    limit: int = 10,
    cursor: str | None = None,
    include_graph: bool = False,
) -> dict[str, Any]:
    """Search the knowledge base using hybrid search."""
    try:
        from metronix.retrieval.search import hybrid_search_and_answer

        # Clamp user-controlled `limit` defensively so an MCP client can't
        # request unbounded result sets. The pipeline currently returns one
        # synthesised answer so `limit` is not propagated downstream, but
        # keeping the clamp here lets us start honouring it without changing
        # the public tool contract.
        limit = min(max(1, limit), 100)  # noqa: F841 — accepted for forward-compat

        # hybrid_search_and_answer returns str (answer with sources appended)
        from metronix.mcp.config import resolve_workspace_id

        answer = await hybrid_search_and_answer(
            query,
            workspace_id=resolve_workspace_id(workspace_id),
            source="mcp",
        )

        # Return the answer directly — the search pipeline already
        # formats results with source citations.
        return SearchResponse(
            results=[
                SearchResultItem(
                    doc_label="",
                    title="Search Result",
                    content=answer,
                    source_type="hybrid_search",
                    score=1.0,
                ).model_dump(),
            ],
            has_more=False,
            next_cursor=None,
            total=1,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metronix_search", e)
        return {"error": error.to_dict()}
