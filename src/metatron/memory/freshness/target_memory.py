"""MemoryTarget adapter — wraps MemoryPostgresStore + MemoryQdrantStore.

MTRNIX-313 (Phase B): lets the Phase A memory freshness stages run unchanged
through the generic pipeline by translating the generic
:class:`~metatron.freshness.targets.FreshnessTarget` calls into the concrete
memory store operations that Phase A used directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

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
            return await result  # type: ignore[no-any-return]
        return result  # type: ignore[return-value]

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
        kwargs: dict[str, object] = {}
        if status is not None:
            kwargs["status"] = status
        if freshness_score is not None:
            kwargs["freshness_score"] = freshness_score
        if superseded_by is not None:
            kwargs["superseded_by"] = superseded_by
        if evidence_count is not None:
            kwargs["evidence_count"] = evidence_count
        if verification_state is not None:
            kwargs["verification_state"] = verification_state
        if valid_until is not None:
            kwargs["valid_until"] = valid_until
        if single_tag is not None:
            kwargs["append_tag"] = single_tag
        if append_tags:
            kwargs["append_tags"] = append_tags
        # ``last_freshness_run_at`` is not persisted on memory_records in
        # Phase B — ignored on write.
        _ = last_freshness_run_at
        await self._pg.update_lifecycle(workspace_id, target_id, **kwargs)

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
        # Memory does not mirror status onto Qdrant chunk payloads in Phase B.
        # Kept for interface symmetry; KB adapter overrides.
        return None
