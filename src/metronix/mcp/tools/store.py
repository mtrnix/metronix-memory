"""MCP tool: metronix_store — store a document."""

from __future__ import annotations

import uuid
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
        from metronix.core.models import Document
        from metronix.ingestion.pipeline import ingest_documents
        from metronix.ingestion.sync import persist_raw_documents
        from metronix.mcp.tools._source_deps import get_store

        # Reject empty AND whitespace-only content: the pipeline skips blank
        # bodies (no chunks), so accepting it would write a raw_documents row and
        # mark it qdrant_synced while nothing is actually indexed.
        if not content or not content.strip():
            raise ValueError("content is required")

        if not doc_label:
            doc_label = f"MEM-{uuid.uuid4().hex[:8].upper()}"

        ws_id = workspace_id or "default"
        doc = Document(
            title=title or doc_label,
            content=content,
            source_type="memory",
            source_id=doc_label,
            workspace_id=ws_id,
            # Treat MCP-stored docs as knowledge base so they are eligible for
            # KB freshness, same as connector/upload sources.
            source_role="knowledge_base",
            metadata=metadata or {},
        )

        # Persist a raw_documents row (source of truth) so an MCP-stored doc is
        # a first-class source like connector and upload docs. connection_id is
        # None — there is no managed connection behind an MCP push.
        #
        # Then index into Qdrant for THIS document only (incremental=True so a
        # re-store under the same doc_label drops the stale chunks first) and
        # mark it qdrant-synced. Embedding is fast and keeps the call
        # synchronous, so the document is searchable on return and chunks_stored
        # is accurate.
        #
        # Graph extraction is deliberately deferred (skip_graph=True, and we do
        # NOT mark graph_synced). It is LLM-bound — ~minutes per document — so
        # doing it inline (let alone the whole-workspace process_all_unsynced_
        # graphs that ingestion.sync.sync_documents_to_stores runs) would block
        # the MCP call and make bulk stores unusable. The batch graph processor
        # (make graph-process, a connector sync, or the admin reindex) picks up
        # graph_synced=false rows later in batches — the same deferred-graph
        # model the connector path already uses.
        #
        # Reuse the process-cached store (shared with the source tools) rather
        # than spinning up a fresh engine/pool per call; do NOT close it.
        store = get_store()
        await persist_raw_documents(store, ws_id, "memory", None, [doc])
        result = await ingest_documents(
            [doc],
            ws_id,
            connector_type="memory",
            source_role="knowledge_base",
            skip_graph=True,
            incremental=True,
        )
        await store.mark_documents_synced_by_source(
            workspace_id=ws_id,
            connector_type="memory",
            source_ids=[doc.source_id],
            target="qdrant",
        )

        return StoreResponse(
            success=len(result.errors) == 0,
            doc_label=doc_label,
            chunks_stored=result.documents_new,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metronix_store", e)
        return {"error": error.to_dict()}
