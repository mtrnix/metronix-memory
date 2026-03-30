"""Ingestion pipeline orchestrator: parse -> chunk -> dedup -> embed -> store.

Takes raw Documents from connectors, processes them through the full
pipeline, and stores the results in vector + graph stores.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import structlog

from metatron.core.interfaces import (
    LLMProviderInterface,
    ProcessorInterface,
    VectorStoreInterface,
)
from metatron.core.models import Chunk, Document, SyncResult
from metatron.ingestion.chunking import root_child_chunk, simple_chunk
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
        updated_at.year
        if updated_at and isinstance(updated_at, datetime)
        else created_at.year
        if created_at and isinstance(created_at, datetime)
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


async def ingest_documents(
    documents: list[Document],
    workspace_id: str,
    connector_type: str = "",
    incremental: bool = False,
    plugin_manager=None,
    source_role: str = "knowledge_base",
    skip_graph: bool = False,
) -> SyncResult:
    """Ingest documents into Qdrant + Memgraph (async, uses AsyncQdrantVectorStore).

    Pipeline stages:
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
    from metatron.core.config import Settings
    from metatron.storage.qdrant import get_async_hybrid_store

    _settings = Settings()
    t0 = time.time()
    store = await get_async_hybrid_store(workspace_id)
    await store._ensure_collection()
    dedup_index = DeduplicationIndex()
    new_count = 0
    updated_count = 0
    skip_count = 0
    dedup_count = 0
    errors: list[str] = []
    graph_queue: list[tuple[Document, str]] = []

    # Phase 1: chunk, dedup, embed, store to Qdrant (sequential, fast)
    for doc in documents:
        try:
            if not doc.content or not doc.content.strip():
                logger.info(
                    "ingest.skipped",
                    title=doc.title,
                    source_id=doc.source_id,
                    source_type=doc.source_type,
                    reason="empty body",
                )
                skip_count += 1
                continue

            # Incremental: delete old chunks before re-ingesting
            was_updated = False
            if incremental and doc.source_id:
                deleted = await store.delete_by_doc_labels([doc.source_id])
                if deleted > 0:
                    was_updated = True
                    dedup_index.remove_doc(doc.source_id)
                    await asyncio.to_thread(
                        _delete_graph_node,
                        doc.source_id,
                        workspace_id,
                    )

            if _settings.hierarchical_chunking_enabled:
                chunk_objs = root_child_chunk(
                    doc.content,
                    document_id=doc.source_id or "",
                    workspace_id=workspace_id,
                )
            else:
                chunk_objs = simple_chunk(
                    doc.content,
                    document_id=doc.source_id or "",
                    workspace_id=workspace_id,
                )

            doc_date = extract_document_date(
                title=doc.title or "",
                content=doc.content or "",
                updated_at=doc.updated_at,
                created_at=doc.created_at,
            )

            for chunk_obj in chunk_objs:
                chunk = chunk_obj.content
                # Dedup: skip near-duplicate chunks from different documents
                if dedup_index.check_and_add(chunk, doc.source_id):
                    dedup_count += 1
                    logger.debug(
                        "ingest.chunk.duplicate", title=doc.title, source_id=doc.source_id
                    )
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
                    "source_role": doc.source_role or source_role,
                    "chunk_id": chunk_obj.id,
                    "chunk_type": chunk_obj.chunk_type.value,
                    "parent_id": chunk_obj.parent_id or "",
                    **(doc.metadata or {}),
                    "url": doc.url,  # after spread so doc.url takes precedence
                }
                # -- ACL: run pre_index hooks to enrich metadata --
                if plugin_manager:
                    for hook in plugin_manager.get_pipeline_hooks("pre_index"):
                        hook_ctx = await hook(
                            {
                                "document": doc,
                                "metadata": metadata,
                                "workspace_id": workspace_id,
                            }
                        )
                        metadata = hook_ctx.get("metadata", metadata)

                await store.add_document(
                    chunk,
                    metadata=metadata,
                    doc_id=doc.source_id,
                )

            if was_updated:
                updated_count += 1
            else:
                new_count += 1

            # Write chunk hierarchy to Memgraph (graceful degradation)
            if _settings.hierarchical_chunking_enabled:
                await asyncio.to_thread(
                    _write_chunk_hierarchy,
                    chunk_objs,
                    workspace_id,
                    doc.source_id,
                )

            # Register people from any source into alias registry
            await asyncio.to_thread(_register_persons, doc)

            # Collect for Phase 2 graph extraction
            graph_queue.append((doc, workspace_id))

            if (new_count + updated_count) % 50 == 0:
                logger.info(
                    "ingest.progress", new=new_count, updated=updated_count, total=len(documents)
                )

        except Exception as e:
            logger.debug(
                "ingest.skipped", title=doc.title, source_id=doc.source_id, reason=f"error: {e}"
            )
            logger.warning("ingest.document.error", source_id=doc.source_id, error=str(e))
            errors.append(f"{doc.source_id}: {e}")

    # Phase 2: parallel graph extraction (slow LLM calls)
    graph_failed_source_ids: list[str] = []
    if not skip_graph and _settings.graph_extraction_enabled and graph_queue:
        graph_result = await asyncio.to_thread(
            _extract_graphs_parallel,
            graph_queue,
            max_workers=_settings.graph_extraction_workers,
            min_chars=_settings.graph_extraction_min_chars,
        )
        graph_failed_source_ids = graph_result.get("failed_source_ids", [])

    duration_ms = (time.time() - t0) * 1000
    logger.info(
        "ingest.done",
        new=new_count,
        updated=updated_count,
        skipped=skip_count,
        duplicates=dedup_count,
        errors=len(errors),
        duration_ms=round(duration_ms),
    )

    return SyncResult(
        connector_type=connector_type,
        workspace_id=workspace_id,
        documents_fetched=len(documents),
        documents_new=new_count,
        documents_updated=updated_count,
        documents_skipped=skip_count,
        errors=errors,
        duration_ms=duration_ms,
        graph_failed_source_ids=graph_failed_source_ids,
    )


def _write_chunk_hierarchy(
    chunk_objs: list[Chunk],
    workspace_id: str,
    doc_label: str,
) -> None:
    """Write CHILD_OF edges to Memgraph for root-child chunks (best-effort)."""
    try:
        from metatron.core.models import ChunkType
        from metatron.storage.memgraph import write_chunk_hierarchy

        root_ids = [c.id for c in chunk_objs if c.chunk_type == ChunkType.ROOT]
        if not root_ids:
            return

        for root_id in root_ids:
            child_ids = [
                c.id
                for c in chunk_objs
                if c.chunk_type == ChunkType.CHILD and c.parent_id == root_id
            ]
            if child_ids:
                write_chunk_hierarchy(
                    workspace_id=workspace_id,
                    root_chunk_id=root_id,
                    child_chunk_ids=child_ids,
                    doc_label=doc_label,
                )
    except Exception as e:
        logger.warning(
            "ingest.chunk_hierarchy.error",
            doc_label=doc_label,
            error=str(e),
        )


async def process_unsynced_graphs(
    workspace_id: str,
    store,  # PostgresStore
    batch_size: int = 50,
) -> dict[str, int]:
    """Process graph extraction for documents not yet synced to Memgraph.

    Reads raw documents from PostgreSQL and processes them one at a time
    through graph extraction. Designed to run independently from the main
    ingestion pipeline (decoupled graph sync).

    Args:
        workspace_id: Workspace scope.
        store: PostgresStore instance.
        batch_size: Max documents to process per call.

    Returns:
        Dict with counts: {"ok": N, "errors": N, "skipped": N}.
    """
    import json

    ok_count = 0
    error_count = 0
    skipped = 0

    rows = await store.get_unsynced_documents(workspace_id, target="graph", limit=batch_size)

    if not rows:
        return {"ok": 0, "errors": 0, "skipped": 0}

    logger.info(
        "process_unsynced_graphs.start",
        workspace_id=workspace_id,
        batch_size=len(rows),
    )

    for row in rows:
        try:
            # Handle metadata that might be JSON string or dict
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}

            doc = Document(
                source_type=row["connector_type"],
                source_id=row["source_id"],
                title=row.get("title") or "",
                content=row.get("content") or "",
                url=row.get("url") or "",
                author=row.get("author") or "",
                metadata=metadata,
                created_at=row.get("source_created_at") or row.get("created_at"),
                updated_at=row.get("source_updated_at") or row.get("updated_at"),
            )

            if not doc.content or not doc.content.strip():
                skipped += 1
                continue

            # Process one document at a time (sequential).
            # Call the graph writers' internals directly (not the try/except
            # wrappers) so failures propagate and we don't mark as synced.
            if doc.source_type == "jira":
                await asyncio.to_thread(
                    _write_graph_strict,
                    doc,
                    workspace_id,
                    is_jira=True,
                )
            else:
                await asyncio.to_thread(
                    _write_graph_strict,
                    doc,
                    workspace_id,
                    is_jira=False,
                )

            # Mark as synced ONLY on success
            await store.mark_documents_synced_by_source(
                workspace_id=workspace_id,
                connector_type=row["connector_type"],
                source_ids=[row["source_id"]],
                target="graph",
            )
            ok_count += 1

            # Brief pause to let Memgraph stabilize between writes
            await asyncio.sleep(1)

        except Exception as e:
            error_count += 1
            logger.warning(
                "process_unsynced_graphs.doc_error",
                source_id=row.get("source_id"),
                error=str(e),
            )
            # On Memgraph failure, wait longer before retrying next doc
            await asyncio.sleep(5)

    logger.info(
        "process_unsynced_graphs.done",
        workspace_id=workspace_id,
        ok=ok_count,
        errors=error_count,
        skipped=skipped,
    )

    return {"ok": ok_count, "errors": error_count, "skipped": skipped}


def _extract_graphs_parallel(
    graph_queue: list[tuple[Document, str]],
    max_workers: int = 4,
    min_chars: int = 100,
) -> dict[str, int]:
    """Run graph extraction for queued documents in parallel.

    Uses ThreadPoolExecutor to run LLM-based graph extraction concurrently.
    Each graph writer is self-contained with its own Memgraph session.

    Args:
        graph_queue: List of (document, workspace_id) tuples.
        max_workers: Maximum number of concurrent extraction threads.
        min_chars: Minimum content length to attempt graph extraction.

    Returns:
        Dict with counts: {"ok": N, "errors": N, "skipped": N}.
    """
    t0 = time.time()
    ok_count = 0
    error_count = 0
    skipped = 0

    # Filter out short documents; Jira short docs still get structured nodes
    eligible: list[tuple[Document, str]] = []
    jira_struct_only: list[tuple[Document, str]] = []
    for doc, ws_id in graph_queue:
        content_len = len(doc.content or "")
        if content_len < min_chars:
            if doc.source_type == "jira":
                jira_struct_only.append((doc, ws_id))
            else:
                skipped += 1
                logger.debug(
                    "ingest.graph.skipped_short",
                    source_id=doc.source_id,
                    content_len=content_len,
                    min_chars=min_chars,
                )
        else:
            eligible.append((doc, ws_id))

    # Create JiraIssue nodes for short Jira docs (structured fields only, no LLM)
    for doc, ws_id in jira_struct_only:
        try:
            _write_jira_to_graph(doc, ws_id, skip_llm_extraction=True)
            ok_count += 1
        except Exception as e:
            error_count += 1
            logger.warning("ingest.jira_struct.error", source_id=doc.source_id, error=str(e))

    if not eligible:
        logger.info(
            "ingest.graph_parallel.skip_all",
            skipped=skipped,
            jira_struct_only=len(jira_struct_only),
        )
        return {"ok": ok_count, "errors": error_count, "skipped": skipped}

    def _write_graph(doc: Document, ws_id: str) -> str:
        """Write one document to graph, return source_id on success."""
        if doc.source_type == "jira":
            _write_jira_to_graph(doc, ws_id)
        else:
            _write_doc_to_graph(doc, ws_id)
        return doc.source_id

    failed: list[tuple[Document, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_item = {
            pool.submit(_write_graph, doc, ws_id): (doc, ws_id) for doc, ws_id in eligible
        }
        for future in as_completed(future_to_item):
            doc, ws_id = future_to_item[future]
            try:
                future.result()
                ok_count += 1
            except Exception as e:
                error_count += 1
                failed.append((doc, ws_id))
                logger.warning(
                    "ingest.graph_parallel.error", source_id=doc.source_id, error=str(e)
                )

    # Retry failed documents sequentially (Memgraph may have recovered)
    still_failed: list[tuple[Document, str]] = []
    if failed:
        retry_ok = 0
        for doc, ws_id in failed:
            try:
                _write_graph(doc, ws_id)
                retry_ok += 1
                ok_count += 1
                error_count -= 1
            except Exception as e:
                still_failed.append((doc, ws_id))
                logger.warning("ingest.graph_retry.error", source_id=doc.source_id, error=str(e))
        if retry_ok:
            logger.info(
                "ingest.graph_retry.recovered",
                retried=len(failed),
                recovered=retry_ok,
                still_failed=len(still_failed),
            )
    else:
        still_failed = failed

    duration_s = time.time() - t0
    logger.info(
        "ingest.graph_parallel.done",
        ok=ok_count,
        errors=error_count,
        skipped=skipped,
        total=len(graph_queue),
        duration_s=round(duration_s, 1),
        workers=max_workers,
    )
    return {
        "ok": ok_count,
        "errors": error_count,
        "skipped": skipped,
        "failed_source_ids": [doc.source_id for doc, _ in still_failed],
    }


def _write_graph_strict(
    doc: Document,
    workspace_id: str,
    *,
    is_jira: bool = False,
) -> None:
    """Write document to graph, raising on failure (no try/except).

    Used by process_unsynced_graphs() where we need to know if the write
    actually succeeded before marking graph_synced=true.
    """
    if is_jira:
        from metatron.storage.graph_jira import write_jira_graph_to_memgraph

        jira_data = {
            "key": doc.source_id,
            "summary": doc.title,
            "status": doc.metadata.get("status", ""),
            "assignee": doc.metadata.get("assignee"),
            "reporter": doc.metadata.get("reporter"),
            "issuetype": doc.metadata.get("issuetype"),
            "priority": doc.metadata.get("priority"),
            "description": doc.content[:2000],
            "created": doc.metadata.get("created_at_str")
            or (doc.created_at.isoformat() if doc.created_at else None),
            "updated": doc.metadata.get("updated_at_str")
            or (doc.updated_at.isoformat() if doc.updated_at else None),
            "resolved_at": doc.metadata.get("resolved_at_str"),
        }
        write_jira_graph_to_memgraph(
            jira_data,
            doc.content,
            workspace_id=workspace_id,
            doc_label=doc.source_id,
            metadata=doc.metadata,
        )
    else:
        from metatron.storage.memgraph import write_doc_graph_to_memgraph

        doc_date = (
            doc.updated_at.isoformat()
            if doc.updated_at
            else doc.created_at.isoformat()
            if doc.created_at
            else None
        )
        write_doc_graph_to_memgraph(
            text=doc.content[:8000],
            file_name=doc.title or doc.source_id or "untitled",
            user_id=doc.author or "system",
            workspace_id=workspace_id,
            doc_label=doc.source_id,
            doc_date=doc_date,
            metadata=doc.metadata,
        )


def _delete_graph_node(doc_label: str, workspace_id: str) -> None:
    """Delete graph node for a document (best-effort, non-fatal)."""
    try:
        from metatron.storage.graph_ops import delete_document_node

        delete_document_node(doc_label, workspace_id)
    except Exception as e:
        logger.warning("ingest.graph_delete.error", doc_label=doc_label, error=str(e))


_PERSON_FIELDS = [
    ("assignee", "assignee_email"),  # Jira
    ("reporter", "reporter_email"),  # Jira
    ("author", "author_email"),  # Confluence, generic
    ("last_modified_by", "last_modified_by_email"),  # Confluence
    ("creator", "creator_email"),  # Generic / future connectors
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


def _write_jira_to_graph(
    doc: Document, workspace_id: str, skip_llm_extraction: bool = False
) -> None:
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
            "created": doc.metadata.get("created_at_str")
            or (doc.created_at.isoformat() if doc.created_at else None),
            "updated": doc.metadata.get("updated_at_str")
            or (doc.updated_at.isoformat() if doc.updated_at else None),
            "resolved_at": doc.metadata.get("resolved_at_str") or None,
        }
        write_jira_graph_to_memgraph(
            jira_data,
            doc.content,
            workspace_id=workspace_id,
            doc_label=doc.source_id,
            skip_llm_extraction=skip_llm_extraction,
            metadata=doc.metadata,
        )
    except Exception as e:
        logger.warning("ingest.jira_graph.error", source_id=doc.source_id, error=str(e))


def _write_doc_to_graph(doc: Document, workspace_id: str) -> None:
    """Write a non-Jira document (Confluence, upload, etc.) to Memgraph."""
    try:
        from metatron.storage.memgraph import write_doc_graph_to_memgraph

        doc_date = (
            doc.updated_at.isoformat()
            if doc.updated_at
            else doc.created_at.isoformat()
            if doc.created_at
            else None
        )
        write_doc_graph_to_memgraph(
            text=doc.content[:8000],
            file_name=doc.title or doc.source_id or "untitled",
            user_id=doc.author or "system",
            workspace_id=workspace_id,
            doc_label=doc.source_id,
            doc_date=doc_date,
            metadata=doc.metadata,
        )
    except Exception as e:
        logger.warning("ingest.doc_graph.error", source_id=doc.source_id, error=str(e))
