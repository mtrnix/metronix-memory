"""Reconciler stage — flags possible duplicates (MTRNIX-313).

Phase B: generic over the target kind via :class:`FreshnessTarget`. Was
``metronix.memory.freshness.reconciler`` in Phase A.

For each record, queries similar items via the adapter (default cosine
>= 0.85). If a duplicate candidate is found, creates a
``ReviewEntry(reason="possible_duplicate")`` unless one already exists for
the same ``(target_id, related_record_id, target_kind)`` tuple (idempotent
rerun).

Best-effort ``:ALIAS`` graph edge via :meth:`FreshnessTarget.alias_edge` —
failures do not fail the stage.

No lifecycle writes here — the human reviewer (MTRNIX-314) decides whether
to promote the duplicate to SUPERSEDED / CONFLICTED / ARCHIVED.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from metronix.core.events import FRESHNESS_REVIEW_CREATED
from metronix.core.models import MachineEvent, ReviewEntry

if TYPE_CHECKING:
    from metronix.core.events import EventBus
    from metronix.freshness.coordination import CoordinationStore
    from metronix.freshness.targets import FreshnessTarget
    from metronix.storage.freshness_pg import FreshnessStore

logger = structlog.get_logger()


# Phase A compat shim — existing tests import ``alias_link_memory_items``
# from the reconciler module. Forward to the storage-layer helper so the
# import path stays valid via the memory/freshness shim.


def alias_link_memory_items(
    workspace_id: str,
    source_id: str,
    target_id: str,
) -> None:
    """Create (or merge) an ALIAS edge between two MemoryRecord nodes.

    Phase A shim kept here so existing imports resolve via the re-export
    shim at ``metronix.memory.freshness.reconciler``.
    """
    from metronix.storage.neo4j_graph import get_graph_driver

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
        target: FreshnessTarget,
        freshness_store: FreshnessStore,
        coordination: CoordinationStore,
        threshold: float = 0.85,
        lock_ttl: int = 30,
        top_k: int = 10,
        event_bus: EventBus | None = None,
    ) -> None:
        self._target = target
        self._freshness_store = freshness_store
        self._coord = coordination
        self._threshold = threshold
        self._lock_ttl = lock_ttl
        self._top_k = top_k
        self._event_bus = event_bus

    async def run(self, workspace_id: str, target_id: str) -> ReviewEntry | None:
        """Process a single record.

        Returns the (new or pre-existing) ``ReviewEntry`` when a duplicate is
        detected, else ``None``.
        """
        target_kind = self._target.kind
        token = await self._coord.acquire_lock(
            self.STAGE,
            target_id,
            self._lock_ttl,
            target_kind=target_kind,
        )
        if token is None:
            logger.debug(
                "freshness.reconciler.lock_contended",
                workspace_id=workspace_id,
                target_id=target_id,
                target_kind=target_kind,
            )
            return None

        started = time.monotonic()
        try:
            record = await self._target.get(workspace_id, target_id)
            if record is None:
                return None

            hits = await self._target.similarity_search(
                workspace_id,
                record.content,
                top_k=self._top_k,
                agent_id=record.agent_id,
            )
            best: tuple[str, float, str] | None = None
            for hit in hits:
                if not hit.target_id or hit.target_id == target_id:
                    continue
                if hit.score < self._threshold:
                    continue
                if best is None or hit.score > best[1]:
                    best = (hit.target_id, hit.score, hit.content)

            if best is None:
                await self._freshness_store.save_machine_event(
                    MachineEvent(
                        workspace_id=workspace_id,
                        event_type="freshness_stage_completed",
                        target_kind=target_kind,
                        target_id=target_id,
                        payload={
                            "stage": self.STAGE,
                            "result": "clean",
                            "duration_ms": int((time.monotonic() - started) * 1000),
                        },
                    )
                )
                return None

            related_id, score, content = best
            existing = await self._freshness_store.find_review_entry(
                workspace_id,
                target_id=target_id,
                target_kind=target_kind,
                reason=self.REASON,
                related_record_id=related_id,
            )
            if existing is not None:
                return existing
            # MTRNIX-395: a duplicate pair is undirected — when the partner
            # record was processed first it created the mirror entry
            # (target=related_id, related=target_id). Treat that as the same
            # finding so the queue holds one row per pair, not two. (Single
            # worker processes jobs sequentially; a TOCTOU window exists only
            # under multi-worker deployments, accepted for now.)
            mirror = await self._freshness_store.find_review_entry(
                workspace_id,
                target_id=related_id,
                target_kind=target_kind,
                reason=self.REASON,
                related_record_id=target_id,
            )
            if mirror is not None:
                return mirror

            entry = ReviewEntry(
                workspace_id=workspace_id,
                target_id=target_id,
                target_kind=target_kind,
                reason=self.REASON,
                related_record_id=related_id,
                content=content,
                confidence=score,
            )
            saved = await self._freshness_store.save_review_entry(entry)

            await self._target.alias_edge(workspace_id, target_id, related_id)

            await self._freshness_store.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_kind=target_kind,
                    target_id=target_id,
                    payload={
                        "stage": self.STAGE,
                        "result": "review_created",
                        "related_record_id": related_id,
                        "confidence": score,
                        "review_entry_id": saved.id,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    },
                )
            )
            # event_bus wiring deferred to MTRNIX-314 (review queue MCP surface);
            # branch is intentional plumbing.
            if self._event_bus is not None:
                await self._event_bus.emit(
                    FRESHNESS_REVIEW_CREATED,
                    {
                        "workspace_id": workspace_id,
                        "target_id": target_id,
                        "target_kind": target_kind,
                        # ``record_id`` kept for Phase A subscribers.
                        "record_id": target_id,
                        "reason": self.REASON,
                        "review_entry_id": saved.id,
                    },
                )
            return saved
        finally:
            await self._coord.release(self.STAGE, target_id, token, target_kind=target_kind)
