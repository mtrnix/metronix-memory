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
from metatron.core.models import Chunk, Document, SyncResult
from metatron.ingestion.chunking import chunk_text, root_child_chunk
from metatron.ingestion.dedup import is_near_duplicate, simhash
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
) -> SyncResult:
    """Ingest documents into Qdrant + Memgraph (sync, uses existing stores).

    Simplified pipeline that works with the current sync code:
    1. Chunk each document's content
    2. Store each chunk in Qdrant (embedding happens inside add_document)
    3. For Jira documents, also write to Memgraph knowledge graph

    Args:
        documents: Documents fetched from a connector.
        workspace_id: Target workspace for storage.
        connector_type: Source type (e.g. "jira", "confluence").

    Returns:
        SyncResult with ingestion statistics.
    """
    from metatron.storage.qdrant import get_hybrid_store

    t0 = time.time()
    store = get_hybrid_store(workspace_id)
    new_count = 0
    skip_count = 0
    errors: list[str] = []

    for doc in documents:
        try:
            if not doc.content or not doc.content.strip():
                skip_count += 1
                continue

            chunks = chunk_text(doc.content)

            doc_date = extract_document_date(
                title=doc.title or "",
                content=doc.content or "",
                updated_at=doc.updated_at,
                created_at=doc.created_at,
            )

            for chunk in chunks:
                metadata = {
                    "title": doc.title,
                    "type": doc.source_type or connector_type,
                    "source_id": doc.source_id,
                    "doc_label": doc.source_id,
                    "workspace_id": workspace_id,
                    "author": doc.author,
                    "date": doc_date,
                    **(doc.metadata or {}),
                }
                store.add_document(chunk, metadata=metadata, doc_id=doc.source_id)
            new_count += 1

            # Jira: also write to knowledge graph
            if doc.source_type == "jira":
                _write_jira_to_graph(doc, workspace_id)

            if new_count % 50 == 0:
                logger.info("ingest.progress", new=new_count, total=len(documents))

        except Exception as e:
            logger.warning("ingest.document.error", source_id=doc.source_id, error=str(e))
            errors.append(f"{doc.source_id}: {e}")

    duration_ms = (time.time() - t0) * 1000
    logger.info("ingest.done", new=new_count, skipped=skip_count,
                errors=len(errors), duration_ms=round(duration_ms))

    return SyncResult(
        connector_type=connector_type,
        workspace_id=workspace_id,
        documents_fetched=len(documents),
        documents_new=new_count,
        documents_skipped=skip_count,
        errors=errors,
        duration_ms=duration_ms,
    )


def _write_jira_to_graph(doc: Document, workspace_id: str) -> None:
    """Write a Jira document to Memgraph knowledge graph."""
    try:
        from metatron.connectors.jira_processing import process_jira_issue
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
