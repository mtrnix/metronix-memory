"""Ingestion pipeline orchestrator: parse -> chunk -> dedup -> embed -> store.

Takes raw Documents from connectors, processes them through the full
pipeline, and stores the results in vector + graph stores.
"""

from __future__ import annotations

import time
from datetime import datetime

import structlog

from metatron.core.interfaces import (
    LLMProviderInterface,
    ProcessorInterface,
    VectorStoreInterface,
)
from metatron.core.models import Document, SyncResult
from metatron.ingestion.chunking import chunk_text
from metatron.ingestion.dedup import DeduplicationIndex, simhash
from metatron.ingestion.processors.dates import extract_date_from_text

logger = structlog.get_logger()


def extract_document_date(
    title: str,
    content: str,
    updated_at: datetime | None = None,
    created_at: datetime | None = None,
) -> str:
    """Extract the most relevant date for a document.

    Priority:
    1. Date from title (most reliable — "2026-01-27 Summary")
    2. First meaningful date from content (first 500 chars)
    3. Fallback: updated_at
    4. Last resort: created_at

    Returns: YYYY-MM-DD string, or "" if no date found.
    """
    fallback_year = (
        updated_at.year if updated_at and isinstance(updated_at, datetime)
        else created_at.year if created_at and isinstance(created_at, datetime)
        else None
    )

    # 1. Try title
    if title:
        d = extract_date_from_text(title, fallback_year=fallback_year)
        if d:
            return d

    # 2. Try first 500 chars of content
    if content:
        d = extract_date_from_text(content[:500], fallback_year=fallback_year)
        if d:
            return d

    # 3. Fallback to timestamps
    if updated_at and isinstance(updated_at, datetime):
        return updated_at.strftime("%Y-%m-%d")
    if created_at and isinstance(created_at, datetime):
        return created_at.strftime("%Y-%m-%d")

    return ""


class IngestionPipeline:
    """Orchestrates the full document ingestion flow.

    Pipeline stages:
    1. Parse: Extract text from documents using appropriate processor.
    2. Chunk: Split text into root-child chunks (OpenMemory pattern).
    3. Dedup: SimHash near-duplicate detection to skip redundant content.
    4. Embed: Generate embeddings via LLM provider.
    5. Store: Upsert chunks into vector store.
    """

    def __init__(
        self,
        vector_store: VectorStoreInterface,
        llm_provider: LLMProviderInterface,
        processors: list[ProcessorInterface] | None = None,
        embedding_dim: int = 768,
    ) -> None:
        self._vector_store = vector_store
        self._llm = llm_provider
        self._processors = processors or []
        self._embedding_dim = embedding_dim

    async def ingest(
        self,
        workspace_id: str,
        documents: list[Document],
    ) -> SyncResult:
        """Run the full ingestion pipeline on a batch of documents.

        Args:
            workspace_id: Target workspace (determines Qdrant collection).
            documents: Documents fetched from a connector.

        Returns:
            SyncResult with counts of processed/skipped/errored documents.
        """
        logger.info(
            "ingestion.pipeline.started",
            workspace_id=workspace_id,
            document_count=len(documents),
        )
        # TODO: implement full pipeline
        # 1. Ensure vector collection exists
        # 2. For each document:
        #    a. Parse content (find matching processor by content type)
        #    b. Chunk with root_child_chunk()
        #    c. Compute simhash for each chunk
        #    d. Dedup: skip chunks that are near-duplicates of existing
        #    e. Batch chunks for embedding
        # 3. Embed all new chunks in batches (self._llm.embed())
        # 4. Upsert to vector store (self._vector_store.upsert())
        # 5. Build and return SyncResult
        raise NotImplementedError("Ingestion pipeline not yet implemented")


def ingest_documents(
    documents: list[Document],
    workspace_id: str,
    connector_type: str = "",
    incremental: bool = False,
) -> SyncResult:
    """Ingest documents into Qdrant + Memgraph (sync, uses existing stores).

    Simplified pipeline that works with the current sync code:
    1. (Incremental) Delete old chunks for each document being re-ingested
    2. Chunk each document's content
    3. Store each chunk in Qdrant (embedding happens inside add_document)
    4. For Jira documents, also write to Memgraph knowledge graph

    Args:
        documents: Documents fetched from a connector.
        workspace_id: Target workspace for storage.
        connector_type: Source type (e.g. "jira", "confluence").
        incremental: If True, delete old chunks before re-ingesting each doc.

    Returns:
        SyncResult with ingestion statistics.
    """
    from metatron.storage.qdrant import get_hybrid_store

    t0 = time.time()
    store = get_hybrid_store(workspace_id)
    dedup_index = DeduplicationIndex()
    new_count = 0
    updated_count = 0
    skip_count = 0
    dedup_count = 0
    errors: list[str] = []

    for doc in documents:
        try:
            if not doc.content or not doc.content.strip():
                logger.debug("ingest.skipped", title=doc.title, source_id=doc.source_id, reason="empty body")
                skip_count += 1
                continue

            # Incremental: delete old chunks before re-ingesting
            was_updated = False
            if incremental and doc.source_id:
                deleted = store.delete_by_doc_labels([doc.source_id])
                if deleted > 0:
                    was_updated = True
                    dedup_index.remove_doc(doc.source_id)
                    _delete_graph_node(doc.source_id, workspace_id)

            chunks = chunk_text(doc.content)

            doc_date = extract_document_date(
                title=doc.title or "",
                content=doc.content or "",
                updated_at=doc.updated_at,
                created_at=doc.created_at,
            )

            for chunk in chunks:
                # Dedup: skip near-duplicate chunks from different documents
                if dedup_index.check_and_add(chunk, doc.source_id):
                    dedup_count += 1
                    logger.debug("ingest.chunk.duplicate", title=doc.title,
                                 source_id=doc.source_id)
                    continue

                chunk_hash = simhash(chunk)
                metadata = {
                    "title": doc.title,
                    "type": doc.source_type or connector_type,
                    "source_id": doc.source_id,
                    "doc_label": doc.source_id,
                    "workspace_id": workspace_id,
                    "author": doc.author,
                    "date": doc_date,
                    "simhash": chunk_hash,
                    **(doc.metadata or {}),
                }
                store.add_document(chunk, metadata=metadata, doc_id=doc.source_id)

            if was_updated:
                updated_count += 1
            else:
                new_count += 1

            # Register people from any source into alias registry
            _register_persons(doc)

            # Write to knowledge graph
            if doc.source_type == "jira":
                _write_jira_to_graph(doc, workspace_id)
            else:
                _write_doc_to_graph(doc, workspace_id)

            if (new_count + updated_count) % 50 == 0:
                logger.info("ingest.progress", new=new_count, updated=updated_count,
                            total=len(documents))

        except Exception as e:
            logger.debug("ingest.skipped", title=doc.title, source_id=doc.source_id, reason=f"error: {e}")
            logger.warning("ingest.document.error", source_id=doc.source_id, error=str(e))
            errors.append(f"{doc.source_id}: {e}")

    duration_ms = (time.time() - t0) * 1000
    logger.info("ingest.done", new=new_count, updated=updated_count,
                skipped=skip_count, duplicates=dedup_count,
                errors=len(errors), duration_ms=round(duration_ms))

    return SyncResult(
        connector_type=connector_type,
        workspace_id=workspace_id,
        documents_fetched=len(documents),
        documents_new=new_count,
        documents_updated=updated_count,
        documents_skipped=skip_count,
        errors=errors,
        duration_ms=duration_ms,
    )


def _delete_graph_node(doc_label: str, workspace_id: str) -> None:
    """Delete graph node for a document (best-effort, non-fatal)."""
    try:
        from metatron.storage.graph_ops import delete_document_node
        delete_document_node(doc_label, workspace_id)
    except Exception as e:
        logger.warning("ingest.graph_delete.error", doc_label=doc_label, error=str(e))


_PERSON_FIELDS = [
    ("assignee", "assignee_email"),       # Jira
    ("reporter", "reporter_email"),       # Jira
    ("author", "author_email"),           # Confluence, generic
    ("last_modified_by", "last_modified_by_email"),  # Confluence
    ("creator", "creator_email"),         # Generic / future connectors
]


def _register_persons(doc: Document) -> None:
    """Register people from document metadata in the alias registry (best-effort).

    Scans well-known person fields (assignee, reporter, author, creator)
    so any connector that puts names in metadata is picked up automatically.
    """
    try:
        from metatron.retrieval.alias_registry import get_alias_registry

        registry = get_alias_registry()
        meta = doc.metadata or {}
        for name_field, email_field in _PERSON_FIELDS:
            name = meta.get(name_field)
            if name and name.strip():
                registry.register_person(
                    display_name=name,
                    email=meta.get(email_field) or None,
                )
    except Exception as e:
        logger.warning("ingest.alias_register.error", source_id=doc.source_id, error=str(e))


def _write_jira_to_graph(doc: Document, workspace_id: str) -> None:
    """Write a Jira document to Memgraph knowledge graph."""
    try:
        from metatron.storage.graph_jira import write_jira_graph_to_memgraph

        # Re-parse structured data from metadata if available
        jira_data = {
            "key": doc.source_id,
            "summary": doc.title,
            "status": doc.metadata.get("status", ""),
            "assignee": doc.metadata.get("assignee"),
            "reporter": doc.metadata.get("reporter"),
            "issuetype": doc.metadata.get("issuetype"),
            "priority": doc.metadata.get("priority"),
            "description": doc.content[:2000],
        }
        write_jira_graph_to_memgraph(
            jira_data, doc.content,
            workspace_id=workspace_id,
            doc_label=doc.source_id,
        )
    except Exception as e:
        logger.warning("ingest.jira_graph.error", source_id=doc.source_id, error=str(e))


def _write_doc_to_graph(doc: Document, workspace_id: str) -> None:
    """Write a non-Jira document (Confluence, upload, etc.) to Memgraph."""
    try:
        from metatron.storage.memgraph import write_doc_graph_to_memgraph

        write_doc_graph_to_memgraph(
            text=doc.content[:8000],
            file_name=doc.title or doc.source_id or "untitled",
            user_id=doc.author or "system",
            workspace_id=workspace_id,
            doc_label=doc.source_id,
        )
    except Exception as e:
        logger.warning("ingest.doc_graph.error", source_id=doc.source_id, error=str(e))
