"""MCP tool implementations for Metatron.

Provides the core MCP tools: search, get, store, and status.
Each tool includes detailed descriptions for LLM tool selection.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from metatron.mcp.server import mcp
from metatron.mcp.errors import MCPError, handle_tool_error, ErrorCode
from metatron.mcp.pagination import CursorPager


# --- Request/Response Models ---

class SearchParams(BaseModel):
    """Parameters for metatron_search tool."""

    query: str = Field(description="Natural language search query")
    workspace_id: Optional[str] = Field(
        default=None,
        description="Workspace ID to search in (uses default if not specified)"
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of results to return"
    )
    cursor: Optional[str] = Field(
        default=None,
        description="Cursor from previous search response for pagination"
    )
    include_graph: bool = Field(
        default=False,
        description="Include knowledge graph context in results"
    )


class SearchResultItem(BaseModel):
    """Single search result item."""

    doc_label: str
    title: str
    content: str
    source_type: str
    timestamp: Optional[str] = None
    score: float = 0.0


class SearchResponse(BaseModel):
    """Response from metatron_search tool."""

    results: list[SearchResultItem]
    has_more: bool
    next_cursor: Optional[str] = None
    total: int


class GetParams(BaseModel):
    """Parameters for metatron_get tool."""

    doc_label: str = Field(description="Unique document label (e.g., 'JIRA-123', 'CONF-456')")
    workspace_id: Optional[str] = Field(
        default=None,
        description="Workspace ID (uses default if not specified)"
    )


class DocumentResponse(BaseModel):
    """Response from metatron_get tool."""

    doc_label: str
    title: str
    content: str
    source_type: str
    timestamp: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StoreParams(BaseModel):
    """Parameters for metatron_store tool."""

    content: str = Field(description="Document content to store")
    title: Optional[str] = Field(default=None, description="Document title")
    workspace_id: Optional[str] = Field(
        default=None,
        description="Workspace ID (uses default if not specified)"
    )
    doc_label: Optional[str] = Field(
        default=None,
        description="Optional unique label for the document"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata to store with the document"
    )


class StoreResponse(BaseModel):
    """Response from metatron_store tool."""

    success: bool
    doc_label: str
    chunks_stored: int


class StatusParams(BaseModel):
    """Parameters for metatron_status tool."""

    workspace_id: Optional[str] = Field(
        default=None,
        description="Workspace ID (uses default if not specified)"
    )


class StatusResponse(BaseModel):
    """Response from metatron_status tool."""

    status: str
    documents: dict[str, int]
    last_sync: Optional[str] = None
    embedding_model: str


# --- Tool Functions ---

@mcp.tool(description="""Search the knowledge base using hybrid RAG (vector + BM25 + knowledge graph).

**Use this tool when:** User wants to find information in the team's knowledge base with natural language.

**Parameters:**
- query: Natural language question or search term (required)
- workspace_id: Specific workspace to search (optional, uses default)
- limit: Results per page (1-100, default 10)
- cursor: Pagination cursor from previous response (optional)
- include_graph: Include knowledge graph context (default false)

**Returns:** List of relevant documents with title, content, source, and score.

**Example:** "Find documentation about the authentication system" """)
async def metatron_search(
    query: str,
    workspace_id: Optional[str] = None,
    limit: int = 10,
    cursor: Optional[str] = None,
    include_graph: bool = False,
) -> dict[str, Any]:
    """Search the knowledge base using hybrid search.

    Delegates to retrieval.search.hybrid_search_and_answer for full pipeline,
    or uses lower-level search for structured results.
    """
    try:
        # Import here to avoid circular imports
        from metatron.retrieval.search import hybrid_search_and_answer
        from metatron.mcp.pagination import CursorPager

        # Clamp limit
        limit = min(max(1, limit), 100)

        # Execute search (sync function, wrap in asyncio)
        import asyncio
        results, answer = await asyncio.to_thread(
            hybrid_search_and_answer,
            query,
            workspace_id or "default",
        )

        # Format results for MCP response
        search_results = []
        for r in results:
            search_results.append(SearchResultItem(
                doc_label=r.get("doc_label", ""),
                title=r.get("title", ""),
                content=r.get("content", "")[:500],  # Truncate for response
                source_type=r.get("source_type", "unknown"),
                timestamp=r.get("timestamp"),
                score=r.get("score", 0.0),
            ))

        # Paginate results
        pager = CursorPager(limit=limit)
        paginated = pager.paginate(search_results, cursor=cursor)

        return SearchResponse(
            results=[r.model_dump() for r in paginated.items],
            has_more=paginated.has_more,
            next_cursor=paginated.next_cursor,
            total=paginated.total or len(search_results),
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metatron_search", e)
        return {"error": error.to_dict()}


@mcp.tool(description="""Retrieve a specific document by its unique label.

**Use this tool when:** User provides a specific document identifier like JIRA-123 or CONF-456.

**Parameters:**
- doc_label: Unique document label (e.g., 'MTRNIX-42', 'DOC-100')
- workspace_id: Workspace containing the document (optional)

**Returns:** Full document content with metadata.

**Example:** "Show me the document PROJ-123" """)
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
                    hint="Check the document label is correct or use search to find documents",
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


@mcp.tool(description="""Store a new document or memory in the knowledge base.

**Use this tool when:** User wants to save information for future retrieval.

**Parameters:**
- content: Document content (required)
- title: Optional document title
- workspace_id: Target workspace (optional, uses default)
- doc_label: Optional unique identifier (auto-generated if not provided)
- metadata: Additional key-value metadata

**Returns:** Success status, document label, and chunk count.

**Example:** "Remember that the API endpoint is /api/v1/chat" """)
async def metatron_store(
    content: str,
    title: Optional[str] = None,
    workspace_id: Optional[str] = None,
    doc_label: Optional[str] = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a new document in the knowledge base."""
    try:
        from metatron.ingestion.pipeline import ingest_documents
        from metatron.core.models import Document

        if not content:
            raise ValueError("content is required")

        # Generate doc_label if not provided
        if not doc_label:
            import uuid
            doc_label = f"MEM-{uuid.uuid4().hex[:8].upper()}"

        # Create document
        doc = Document(
            doc_label=doc_label,
            title=title or doc_label,
            content=content,
            source_type="memory",
            source_id=doc_label,
            workspace_id=workspace_id or "default",
            metadata=metadata or {},
        )

        # Ingest document
        result = await asyncio.to_thread(
            ingest_documents,
            [doc],
            workspace_id or "default",
            connector_type="memory",
            incremental=False,
        )

        return StoreResponse(
            success=result.success,
            doc_label=doc_label,
            chunks_stored=result.new_chunks,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metatron_store", e)
        return {"error": error.to_dict()}


@mcp.tool(description="""Check system health and workspace status.

**Use this tool when:** User asks about system status, document counts, or last sync time.

**Parameters:**
- workspace_id: Workspace to check (optional, uses default)

**Returns:** Health status, document counts by source, last sync timestamp, embedding model.

**Example:** "What's the status of the system?" """)
async def metatron_status(
    workspace_id: Optional[str] = None,
) -> dict[str, Any]:
    """Check system health and status."""
    try:
        from metatron.storage.qdrant import get_hybrid_store
        from metatron.core.config import Settings

        ws_id = workspace_id or "default"
        settings = Settings()

        # Try to get store and count documents
        try:
            store = get_hybrid_store(ws_id)
            # Get counts by source type
            all_results = store.search_all(limit=1000)

            counts: dict[str, int] = {"total": len(all_results)}
            for doc in all_results:
                src = doc.get("source_type", "unknown")
                counts[src] = counts.get(src, 0) + 1

        except Exception:
            counts = {"total": 0}

        return StatusResponse(
            status="healthy" if counts.get("total", 0) > 0 else "initializing",
            documents=counts,
            last_sync=None,  # TODO: Get from sync metadata
            embedding_model=settings.embedding_model,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metatron_status", e)
        return {"error": error.to_dict()}


# Need to import asyncio for the store function
import asyncio
