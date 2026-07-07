"""Shared helper for storing a single document into the knowledge base.

Used by both the metronix_store MCP tool (metronix/mcp/tools/store.py) and
the POST /api/v1/knowledge/store REST route (metronix/api/routes/knowledge.py)
so the two entry points can never drift apart.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from metronix.storage.postgres import PostgresStore


async def store_document(
    store: PostgresStore,
    *,
    workspace_id: str,
    content: str,
    title: str | None = None,
    doc_label: str | None = None,
    source_type: str = "memory",
    metadata: dict[str, Any] | None = None,
) -> tuple[bool, str, int]:
    """Chunk, embed, and index one document into the knowledge base.

    Persists a raw_documents row (source of truth), indexes it into Qdrant
    for this document only (incremental=True drops stale chunks first on a
    re-store under the same doc_label), and marks it Qdrant-synced. Graph
    extraction is deliberately deferred (skip_graph=True) — it is LLM-bound
    and would block a synchronous store call; the batch graph processor
    picks up graph_synced=false rows later.

    Returns (success, doc_label, chunks_stored). Raises ValueError if
    content is empty/whitespace-only — callers must check this before
    acquiring a store handle; the pipeline skips blank bodies (no chunks),
    so accepting it would write a raw_documents row and mark it
    qdrant_synced while nothing is actually indexed.
    """
    # Lazy imports: metronix.ingestion.sync.persist_raw_documents and
    # metronix.ingestion.pipeline.ingest_documents are patched directly by
    # unit tests. Importing them at call time (not module load time) is
    # what lets those patches take effect regardless of which caller
    # (MCP tool, REST route, migration script) invokes this function.
    from metronix.core.models import Document
    from metronix.ingestion.pipeline import ingest_documents
    from metronix.ingestion.sync import persist_raw_documents

    if not content or not content.strip():
        raise ValueError("content is required")

    if not doc_label:
        doc_label = f"MEM-{uuid.uuid4().hex[:8].upper()}"

    doc = Document(
        title=title or doc_label,
        content=content,
        source_type=source_type,
        source_id=doc_label,
        workspace_id=workspace_id,
        source_role="knowledge_base",
        metadata=metadata or {},
    )

    await persist_raw_documents(store, workspace_id, source_type, None, [doc])
    result = await ingest_documents(
        [doc],
        workspace_id,
        connector_type=source_type,
        source_role="knowledge_base",
        skip_graph=True,
        incremental=True,
    )
    await store.mark_documents_synced_by_source(
        workspace_id=workspace_id,
        connector_type=source_type,
        source_ids=[doc.source_id],
        target="qdrant",
    )

    return len(result.errors) == 0, doc_label, result.documents_new
