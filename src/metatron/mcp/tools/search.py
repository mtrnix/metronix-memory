"""MCP tool: metatron_search — hybrid RAG search."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from metatron.mcp.errors import handle_tool_error
from metatron.mcp.pagination import CursorPager
from metatron.mcp.server import mcp
from metatron.mcp.tools.models import SearchResponse, SearchResultItem


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
async def metatron_search(
    query: str,
    workspace_id: Optional[str] = None,
    limit: int = 10,
    cursor: Optional[str] = None,
    include_graph: bool = False,
) -> dict[str, Any]:
    """Search the knowledge base using hybrid search."""
    try:
        from metatron.retrieval.search import hybrid_search_and_answer

        limit = min(max(1, limit), 100)

        # hybrid_search_and_answer returns str (answer with sources appended)
        answer = await asyncio.to_thread(
            hybrid_search_and_answer,
            query,
            workspace_id or "default",
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
        error = handle_tool_error("metatron_search", e)
        return {"error": error.to_dict()}
