"""MemoryTarget adapter — wraps MemoryPostgresStore + MemoryQdrantStore.

MTRNIX-313 (Phase B): lets the Phase A memory freshness stages run unchanged
through the generic pipeline by translating the generic
:class:`~metatron.freshness.targets.FreshnessTarget` calls into the concrete
memory store operations that Phase A used directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from metatron.freshness import metrics
from metatron.freshness.targets import FreshnessTargetRecord, SimilarityHit

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from datetime import datetime

    from metatron.core.models import LifecycleStatus
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

logger = structlog.get_logger()


# Accept both sync and async factories so the worker can plug in a cached
# sync callable (Phase A path) or an ``async def`` factory (future).
MemoryQdrantFactory = Callable[[str], "MemoryQdrantStore | Awaitable[MemoryQdrantStore]"]


class MemoryTarget:
    """Adapter implementing :class:`FreshnessTarget` over the memory stores."""

    kind = "memory_record"
    supports_candidate_promotion = True

    def __init__(
        self,
        *,
        pg_store: MemoryPostgresStore,
        qdrant_store_factory: MemoryQdrantFactory,
    ) -> None:
        self._pg = pg_store
        self._qdrant_factory = qdrant_store_factory

    async def _resolve_qdrant(self, workspace_id: str) -> MemoryQdrantStore:
        result = self._qdrant_factory(workspace_id)
        if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
            return await result
        return result

    async def get(self, workspace_id: str, target_id: str) -> FreshnessTargetRecord | None:
        rec = await self._pg.get(workspace_id, target_id)
        if rec is None:
            return None
        return FreshnessTargetRecord(
            target_id=rec.id,
            workspace_id=rec.workspace_id,
            content=rec.content,
            tags=list(rec.tags),
            status=rec.status,
            freshness_score=rec.freshness_score,
            superseded_by=rec.superseded_by,
            valid_until=rec.valid_until,
            updated_at=rec.updated_at,
            evidence_count=rec.evidence_count,
            verification_state=rec.verification_state,
            # ``last_freshness_run_at`` is not persisted on memory_records in
            # Phase B — the age-gate is KB-specific. Exposed on the DTO for
            # symmetry; for memory it is always ``None``.
            last_freshness_run_at=getattr(rec, "last_freshness_run_at", None),
            agent_id=rec.agent_id or None,
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
        # ``append_tag`` from :func:`apply_decision` is a comma-joined batch
        # — split back into a list so MemoryPostgresStore does a single
        # idempotent SQL-side union.
        append_tags: list[str] | None = None
        single_tag: str | None = None
        if append_tag:
            if "," in append_tag:
                append_tags = [t for t in append_tag.split(",") if t]
            else:
                single_tag = append_tag
        # ``last_freshness_run_at`` is not persisted on memory_records in
        # Phase B — silently dropped (KB-only column).
        del last_freshness_run_at
        await self._pg.update_lifecycle(
            workspace_id,
            target_id,
            status=status,
            freshness_score=freshness_score,
            superseded_by=superseded_by,
            evidence_count=evidence_count,
            verification_state=verification_state,
            valid_until=valid_until,
            append_tag=single_tag,
            append_tags=append_tags,
        )

    async def similarity_search(
        self,
        workspace_id: str,
        content: str,
        *,
        top_k: int,
        agent_id: str | None = None,
    ) -> list[SimilarityHit]:
        qdrant = await self._resolve_qdrant(workspace_id)
        hits = await qdrant.search(content, agent_id=agent_id, top_k=top_k)
        out: list[SimilarityHit] = []
        for h in hits:
            hit_id = str(h.get("record_id") or "")
            if not hit_id:
                continue
            out.append(
                SimilarityHit(
                    target_id=hit_id,
                    score=float(h.get("score") or 0.0),
                    content=str(h.get("content") or ""),
                )
            )
        return out

    async def link_edges_batch(
        self,
        workspace_id: str,
        source_id: str,
        edges: list[tuple[str, float]],
    ) -> None:
        from metatron.storage.memory_graph import link_memory_items_batch

        if not edges:
            return
        batch = [(source_id, dst, score) for dst, score in edges]
        try:
            await asyncio.to_thread(link_memory_items_batch, workspace_id, batch)
        except Exception:
            logger.warning(
                "freshness.memory_target.link_edges_failed",
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
        # Phase A wrote a MemoryRecord :ALIAS edge — keep that behaviour.
        from metatron.freshness.stages.reconciler import alias_link_memory_items

        try:
            await asyncio.to_thread(alias_link_memory_items, workspace_id, source_id, target_id)
        except Exception:
            logger.warning(
                "freshness.memory_target.alias_failed",
                workspace_id=workspace_id,
                source_id=source_id,
                target_id=target_id,
                exc_info=True,
            )

    async def sync_downstream_stores(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus,
        freshness_score: float,
    ) -> None:
        """Mirror ``memory_records.status`` into the Qdrant point payload.

        Best-effort — Qdrant is a derived store; failures are logged at
        WARNING, counted on the ``freshness_qdrant_sync_failed_total``
        counter, and never propagate. PG remains the source of truth;
        the backfill script at
        ``scripts/backfill_memory_qdrant_status_payload.py`` is the
        long-tail safety net for persistent drift (MTRNIX-322).

        ``freshness_score`` is accepted for interface symmetry with the
        KB adapter but not written — memory Qdrant points do not carry a
        ``freshness_score`` payload field in this iteration.
        """
        del freshness_score  # documented: not persisted for memory target
        try:
            qdrant = await self._resolve_qdrant(workspace_id)
            await qdrant.update_payload(target_id, {"status": status.value})
        except Exception:
            logger.warning(
                "freshness.memory_target.qdrant_payload_sync_failed",
                workspace_id=workspace_id,
                target_id=target_id,
                status=status.value,
                exc_info=True,
            )
            # Metrics must never bite — swallow any registry/label error.
            with contextlib.suppress(Exception):
                metrics.qdrant_sync_failed.labels(
                    target_kind="memory_record",
                    stage="sync_downstream",
                ).inc()
