"""RawDocumentTarget adapter — KB raw_documents plug-in for the freshness pipeline.

MTRNIX-313 (Phase B): implements :class:`FreshnessTarget` over
:class:`PostgresStore` + :class:`AsyncQdrantVectorStore` so the generic
stages (Linker, Reconciler, FreshnessMonitor, Curator) can run against the
KB surface just like they run against agent memory via
:class:`~metronix.memory.freshness.target_memory.MemoryTarget`.

Key differences from the memory adapter:

* ``supports_candidate_promotion = False`` — KB has no CANDIDATE state in
  Phase B, so the Curator short-circuits immediately for KB jobs.
* ``similarity_search`` deduplicates by ``doc_label`` — Qdrant stores one
  point per chunk and a single raw_document produces multiple chunks.
* ``sync_downstream_stores`` mirrors ``(status, freshness_score)`` onto
  every chunk payload so retrieval can push the ARCHIVED/SUPERSEDED filter
  down to Qdrant without a PG round-trip per hit. Also writes ``status``
  onto the Neo4j ``:Document`` node for graph-side observability.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from metronix.freshness.targets import FreshnessTargetRecord, SimilarityHit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime

    from metronix.core.models import LifecycleStatus
    from metronix.storage.postgres import PostgresStore
    from metronix.storage.qdrant import AsyncQdrantVectorStore

    _QdrantResult = AsyncQdrantVectorStore | Awaitable[AsyncQdrantVectorStore]

logger = structlog.get_logger()


class RawDocumentTarget:
    """Adapter over KB PG + Qdrant + Neo4j for the freshness pipeline.

    Factory may be sync or async so the worker can plug in a sync cached
    callable (Phase A shape) or an ``async def`` builder (for providers that
    must await collection creation on first call).
    """

    kind = "raw_document"
    supports_candidate_promotion = False  # Phase B: no CANDIDATE state for KB

    def __init__(
        self,
        *,
        pg_store: PostgresStore,
        qdrant_factory: Callable[[str], _QdrantResult],
    ) -> None:
        self._pg = pg_store
        self._qdrant_factory = qdrant_factory

    async def _resolve_qdrant(self, workspace_id: str) -> AsyncQdrantVectorStore:
        result = self._qdrant_factory(workspace_id)
        if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
            return await result
        return result

    async def get(self, workspace_id: str, target_id: str) -> FreshnessTargetRecord | None:
        doc = await self._pg.get_raw_document_by_id(workspace_id, target_id)
        if doc is None:
            return None
        # Prefer ``updated_at`` for the freshness clock; fall back to
        # ``fetched_at`` if the row was never edited post-ingest.
        updated = doc.updated_at or doc.fetched_at
        return FreshnessTargetRecord(
            target_id=doc.id,
            workspace_id=doc.workspace_id,
            content=doc.content,
            # KB has no first-class tags list in Phase B — leave empty.
            tags=[],
            status=doc.status,
            freshness_score=doc.freshness_score,
            superseded_by=doc.superseded_by,
            valid_until=doc.valid_until,
            updated_at=updated,
            evidence_count=doc.evidence_count,
            verification_state=doc.verification_state,
            last_freshness_run_at=doc.last_freshness_run_at,
            # Raw documents do not carry an ``agent_id`` — leave None so
            # the adapter's similarity_search does not scope by agent.
            agent_id=None,
        )

    async def update_lifecycle(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus | None = None,
        freshness_score: float | None = None,
        superseded_by: str | None = None,
        evidence_count: int | None = None,
        verification_state: str | None = None,
        valid_until: datetime | None = None,
        last_freshness_run_at: datetime | None = None,
        append_tag: str | None = None,
    ) -> None:
        # Phase B raw_documents has no tags column — silently drop.
        _ = append_tag
        await self._pg.update_raw_document_lifecycle(
            workspace_id,
            target_id,
            status=status,
            freshness_score=freshness_score,
            superseded_by=superseded_by,
            evidence_count=evidence_count,
            verification_state=verification_state,
            valid_until=valid_until,
            last_freshness_run_at=last_freshness_run_at,
        )

    async def similarity_search(
        self,
        workspace_id: str,
        content: str,
        *,
        top_k: int,
        agent_id: str | None = None,
    ) -> list[SimilarityHit]:
        # ``agent_id`` is ignored for KB (no per-agent KB scoping in Phase B).
        _ = agent_id
        qdrant = await self._resolve_qdrant(workspace_id)
        # ``hybrid_search`` returns per-chunk rows; a single raw_document
        # produces multiple chunks. Dedup by doc_label so the generic
        # stages operate on raw_document ids, not chunk ids. Keep highest
        # score per doc (first occurrence wins because hybrid_search returns
        # results already sorted by score desc).
        hits = await qdrant.hybrid_search(content, limit=top_k * 3)
        seen: set[str] = set()
        out: list[SimilarityHit] = []
        for h in hits:
            payload = h.get("payload", h) if isinstance(h, dict) else h
            doc_label = str(payload.get("doc_label") or "") if hasattr(payload, "get") else ""
            if not doc_label or doc_label in seen:
                continue
            seen.add(doc_label)
            out.append(
                SimilarityHit(
                    target_id=doc_label,
                    score=float(h.get("score") or 0.0) if isinstance(h, dict) else 0.0,
                    content=str(payload.get("content") or payload.get("text") or "")
                    if hasattr(payload, "get")
                    else "",
                )
            )
            if len(out) >= top_k:
                break
        return out

    async def link_edges_batch(
        self,
        workspace_id: str,
        source_id: str,
        edges: list[tuple[str, float]],
    ) -> None:
        if not edges:
            return
        from metronix.storage.raw_document_graph import link_raw_documents_batch

        batch = [(source_id, dst, score) for dst, score in edges]
        try:
            await asyncio.to_thread(link_raw_documents_batch, workspace_id, batch)
        except Exception:
            logger.warning(
                "freshness.raw_document_target.link_edges_failed",
                workspace_id=workspace_id,
                source_id=source_id,
                edge_count=len(edges),
                exc_info=True,
            )

    async def alias_edge(
        self,
        workspace_id: str,
        source_id: str,
        target_id: str,
    ) -> None:
        from metronix.storage.raw_document_graph import alias_raw_documents

        try:
            await asyncio.to_thread(alias_raw_documents, workspace_id, source_id, target_id)
        except Exception:
            logger.warning(
                "freshness.raw_document_target.alias_failed",
                workspace_id=workspace_id,
                source_id=source_id,
                target_id=target_id,
                exc_info=True,
            )

    async def list_stale_candidates(
        self,
        workspace_id: str,
        *,
        older_than: datetime,
        limit: int,
    ) -> list[str]:
        """KB scheduled scan is deferred (MTRNIX-316 follow-up).

        Returns an empty list so the shared ``ScheduledScan`` orchestrator
        is a no-op for the KB target kind. Follow-up ticket:
        implement via ``raw_documents.last_freshness_run_at IS NULL OR <
        :older_than`` and wire a second ``ScheduledScan`` in
        ``_build_worker``.
        """
        _ = workspace_id
        _ = older_than
        _ = limit
        return []

    async def sync_downstream_stores(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus,
        freshness_score: float,
    ) -> None:
        """Mirror ``(status, freshness_score)`` into Qdrant payloads + Neo4j.

        Best-effort — any failure is logged and swallowed so the freshness
        pipeline never fails solely because a derived store is momentarily
        unavailable. PG remains the source of truth; a later retry will
        re-sync the payload.

        ``target_id`` is the ``raw_documents.id`` (UUID), but Qdrant chunk
        payloads and Neo4j ``:Document`` nodes are keyed by ``doc_label`` =
        ``raw_documents.source_id`` (Confluence page id, Jira issue key, etc.).
        We resolve the source_id before calling the downstream stores
        (MTRNIX-313 follow-up — without this, the downstream sync was a
        silent no-op because no chunks/nodes match a UUID doc_label).
        """
        doc = await self._pg.get_raw_document_by_id(workspace_id, target_id)
        if doc is None:
            logger.debug(
                "freshness.raw_document_target.sync_downstream_no_record",
                workspace_id=workspace_id,
                target_id=target_id,
            )
            return
        doc_label = doc.source_id
        if not doc_label:
            logger.warning(
                "freshness.raw_document_target.missing_source_id",
                workspace_id=workspace_id,
                target_id=target_id,
            )
            return
        payload = {"status": status.value, "freshness_score": freshness_score}
        try:
            qdrant = await self._resolve_qdrant(workspace_id)
            await qdrant.update_payload_by_doc_label(
                workspace_id=workspace_id,
                doc_label=doc_label,
                payload=payload,
            )
        except Exception:
            logger.warning(
                "freshness.raw_document_target.qdrant_payload_sync_failed",
                workspace_id=workspace_id,
                target_id=target_id,
                doc_label=doc_label,
                exc_info=True,
            )
        try:
            from metronix.storage.raw_document_graph import set_raw_document_status

            await asyncio.to_thread(set_raw_document_status, workspace_id, doc_label, status.value)
        except Exception:
            logger.debug(
                "freshness.raw_document_target.neo4j_status_skipped",
                workspace_id=workspace_id,
                target_id=target_id,
                doc_label=doc_label,
                exc_info=True,
            )
