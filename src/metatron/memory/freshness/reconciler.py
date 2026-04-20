"""Reconciler stage — flags possible duplicates (MTRNIX-304).

For each record, queries Qdrant for very-high-similarity matches (default
cosine >= 0.85). If a duplicate candidate is found, creates a
``ReviewEntry(reason="possible_duplicate")`` — unless one already exists for
the same ``(record_id, related_record_id)`` pair (idempotent rerun).

Best-effort Neo4j ALIAS edge is written so the graph reflects the
relationship; failures do not fail the stage.

No PG lifecycle writes here — the human reviewer (MTRNIX-314) decides
whether to promote the duplicate to SUPERSEDED / CONFLICTED / SUPERSEDED.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from metatron.core.events import FRESHNESS_REVIEW_CREATED
from metatron.core.models import MachineEvent, ReviewEntry

if TYPE_CHECKING:
    from metatron.core.events import EventBus
    from metatron.memory.freshness.coordination import CoordinationStore
    from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

logger = structlog.get_logger()


def alias_link_memory_items(
    workspace_id: str,
    source_id: str,
    target_id: str,
) -> None:
    """Create (or merge) an ALIAS edge between two MemoryRecord nodes."""
    from metatron.storage.neo4j_graph import get_graph_driver

    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (a:MemoryRecord {id: $source, workspace_id: $ws})
            MATCH (b:MemoryRecord {id: $target, workspace_id: $ws})
            MERGE (a)-[:ALIAS]->(b)
            """,
            {"source": source_id, "target": target_id, "ws": workspace_id},
        )


class Reconciler:
    """Flags possible duplicates for human review."""

    STAGE = "reconciler"
    REASON = "possible_duplicate"

    def __init__(
        self,
        *,
        pg_store: MemoryPostgresStore,
        qdrant_store: MemoryQdrantStore,
        freshness_pg: FreshnessPostgresStore,
        coordination: CoordinationStore,
        threshold: float = 0.85,
        lock_ttl: int = 30,
        top_k: int = 10,
        event_bus: EventBus | None = None,
    ) -> None:
        self._pg = pg_store
        self._qdrant = qdrant_store
        self._freshness_pg = freshness_pg
        self._coord = coordination
        self._threshold = threshold
        self._lock_ttl = lock_ttl
        self._top_k = top_k
        self._event_bus = event_bus

    async def run(self, workspace_id: str, record_id: str) -> ReviewEntry | None:
        """Process a single record.

        Returns the (new or pre-existing) ``ReviewEntry`` when a duplicate
        is detected, else ``None``.
        """
        token = await self._coord.acquire_lock(
            self.STAGE, record_id, self._lock_ttl
        )
        if token is None:
            logger.debug(
                "freshness.reconciler.lock_contended",
                workspace_id=workspace_id,
                record_id=record_id,
            )
            return None

        started = time.monotonic()
        try:
            record = await self._pg.get(workspace_id, record_id)
            if record is None:
                return None

            hits = await self._qdrant.search(
                record.content,
                agent_id=record.agent_id or None,
                top_k=self._top_k,
            )
            best: tuple[str, float, str] | None = None
            for hit in hits:
                hit_id = str(hit.get("record_id") or "")
                if not hit_id or hit_id == record_id:
                    continue
                score = float(hit.get("score") or 0.0)
                if score < self._threshold:
                    continue
                content = str(hit.get("content") or "")
                if best is None or score > best[1]:
                    best = (hit_id, score, content)

            if best is None:
                await self._coord.write_checkpoint(
                    self.STAGE, record_id, "clean"
                )
                await self._freshness_pg.save_machine_event(
                    MachineEvent(
                        workspace_id=workspace_id,
                        event_type="freshness_stage_completed",
                        target_id=record_id,
                        payload={
                            "stage": self.STAGE,
                            "result": "clean",
                            "duration_ms": int(
                                (time.monotonic() - started) * 1000
                            ),
                        },
                    )
                )
                return None

            related_id, score, content = best
            existing = await self._freshness_pg.find_review_entry(
                workspace_id,
                record_id=record_id,
                reason=self.REASON,
                related_record_id=related_id,
            )
            if existing is not None:
                return existing

            entry = ReviewEntry(
                workspace_id=workspace_id,
                record_id=record_id,
                reason=self.REASON,
                related_record_id=related_id,
                content=content,
                confidence=score,
            )
            saved = await self._freshness_pg.save_review_entry(entry)

            try:
                await asyncio.to_thread(
                    alias_link_memory_items,
                    workspace_id,
                    record_id,
                    related_id,
                )
            except Exception:
                logger.warning(
                    "freshness.reconciler.neo4j_failed",
                    workspace_id=workspace_id,
                    record_id=record_id,
                    related_record_id=related_id,
                    exc_info=True,
                )

            await self._coord.write_checkpoint(
                self.STAGE, record_id, "review_created"
            )
            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_id=record_id,
                    payload={
                        "stage": self.STAGE,
                        "result": "review_created",
                        "related_record_id": related_id,
                        "confidence": score,
                        "review_entry_id": saved.id,
                        "duration_ms": int(
                            (time.monotonic() - started) * 1000
                        ),
                    },
                )
            )
            if self._event_bus is not None:
                await self._event_bus.emit(
                    FRESHNESS_REVIEW_CREATED,
                    {
                        "workspace_id": workspace_id,
                        "record_id": record_id,
                        "reason": self.REASON,
                        "review_entry_id": saved.id,
                    },
                )
            return saved
        finally:
            await self._coord.release(self.STAGE, record_id, token)
