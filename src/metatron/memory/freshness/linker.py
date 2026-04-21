"""Linker stage — counts related memories and writes LINKED_TO edges.

Given a ``MemoryRecord``, the Linker:

1. Acquires ``freshness:linker:{record_id}`` (lock-per-item).
2. Runs a dense cosine query in Qdrant for the workspace.
3. Filters hits with score >= ``threshold`` (excluding self).
4. Writes ``evidence_count`` back to PG via ``update_lifecycle``.
5. Best-effort creates ``(:MemoryRecord)-[:LINKED_TO]->(:MemoryRecord)`` edges
   in Neo4j via a single ``asyncio.to_thread`` batch call (one session,
   one ``UNWIND`` statement) — avoids N thread-pool tasks per record.
6. Writes a ``freshness_stage_completed`` MachineEvent.

Workspace isolation is strict: PG/Qdrant/Neo4j calls all carry
``workspace_id`` from the record we looked up.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import MachineEvent

if TYPE_CHECKING:
    from collections.abc import Callable

    from metatron.memory.freshness.coordination import CoordinationStore
    from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

    QdrantStoreFactory = Callable[[str], MemoryQdrantStore]

logger = structlog.get_logger()


def link_memory_items_batch(
    workspace_id: str,
    edges: list[tuple[str, str, float]],
) -> None:
    """Create LINKED_TO edges between MemoryRecord nodes in a single session.

    Thin wrapper around the shared storage helper — called via
    ``asyncio.to_thread`` by the Linker stage so up to N edges fan out
    through one Neo4j session instead of N thread-pool tasks.
    """
    from metatron.storage.memory_graph import link_memory_items_batch as _batch

    _batch(workspace_id, edges)


class Linker:
    """Counts related memories and writes graph edges for a single record."""

    STAGE = "linker"

    def __init__(
        self,
        *,
        pg_store: MemoryPostgresStore,
        qdrant_store_factory: QdrantStoreFactory,
        freshness_pg: FreshnessPostgresStore,
        coordination: CoordinationStore,
        threshold: float = 0.6,
        lock_ttl: int = 30,
        top_k: int = 20,
    ) -> None:
        self._pg = pg_store
        self._qdrant_factory = qdrant_store_factory
        self._freshness_pg = freshness_pg
        self._coord = coordination
        self._threshold = threshold
        self._lock_ttl = lock_ttl
        self._top_k = top_k

    async def run(self, workspace_id: str, record_id: str) -> int:
        """Process a single record. Returns ``evidence_count``.

        Returns 0 and exits cleanly if: lock contended, record missing, or
        the Qdrant query produces no hits above threshold.
        """
        token = await self._coord.acquire_lock(self.STAGE, record_id, self._lock_ttl)
        if token is None:
            logger.debug(
                "freshness.linker.lock_contended",
                workspace_id=workspace_id,
                record_id=record_id,
            )
            return 0

        started = time.monotonic()
        try:
            record = await self._pg.get(workspace_id, record_id)
            if record is None:
                return 0

            # Resolve the workspace-scoped Qdrant store. The factory owns
            # caching so repeated calls for the same workspace are cheap.
            qdrant = self._qdrant_factory(workspace_id)

            # Search the same workspace for semantically similar records.
            hits = await qdrant.search(
                record.content,
                agent_id=record.agent_id or None,
                top_k=self._top_k,
            )
            related: list[tuple[str, float]] = []
            for hit in hits:
                hit_id = str(hit.get("record_id") or "")
                if not hit_id or hit_id == record_id:
                    continue
                score = float(hit.get("score") or 0.0)
                if score >= self._threshold:
                    related.append((hit_id, score))

            evidence_count = len(related)
            await self._pg.update_lifecycle(
                workspace_id,
                record_id,
                evidence_count=evidence_count,
            )

            if related:
                edges = [(record_id, hit_id, score) for hit_id, score in related]
                try:
                    await asyncio.to_thread(
                        link_memory_items_batch,
                        workspace_id,
                        edges,
                    )
                except Exception:
                    logger.warning(
                        "freshness.linker.neo4j_failed",
                        workspace_id=workspace_id,
                        record_id=record_id,
                        edge_count=len(edges),
                        exc_info=True,
                    )

            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_id=record_id,
                    payload={
                        "stage": self.STAGE,
                        "evidence_count": evidence_count,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    },
                )
            )
            return evidence_count
        finally:
            await self._coord.release(self.STAGE, record_id, token)
