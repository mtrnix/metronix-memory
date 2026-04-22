"""Linker stage — counts related records and writes graph edges (MTRNIX-313).

Phase B: generic over the target kind via :class:`FreshnessTarget`. Was
``metatron.memory.freshness.linker`` in Phase A.

Flow for a single target_id:

1. Acquire ``freshness:linker:{target_id}`` (lock-per-item, scoped by
   ``target_kind`` for non-memory targets so memory + KB do not collide).
2. Fetch the record via the adapter.
3. Run similarity search via the adapter (Qdrant cosine for memory,
   Qdrant hybrid for KB — adapter decides).
4. Filter hits with score >= ``threshold`` (excluding self).
5. Write ``evidence_count`` back via :meth:`FreshnessTarget.update_lifecycle`.
6. Best-effort graph edges via :meth:`FreshnessTarget.link_edges_batch`.
7. Write a ``freshness_stage_completed`` MachineEvent.

Workspace isolation: every adapter call carries ``workspace_id`` from the
record we looked up.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import MachineEvent

if TYPE_CHECKING:
    from metatron.freshness.coordination import CoordinationStore
    from metatron.freshness.targets import FreshnessTarget
    from metatron.storage.freshness_pg import FreshnessStore

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Phase A compat shim — the Linker used to expose a module-level
# ``link_memory_items_batch`` helper. Some tests and the MemoryTarget
# adapter still import it from here. Keep forwarding to the storage layer.
# ---------------------------------------------------------------------------


def link_memory_items_batch(
    workspace_id: str,
    edges: list[tuple[str, str, float]],
) -> None:
    """Create LINKED_TO edges between MemoryRecord nodes in one session.

    Phase A shim: forwards to :mod:`metatron.storage.memory_graph`. Kept here
    so existing imports (``from metatron.memory.freshness.linker import
    link_memory_items_batch``) still resolve via the re-export shim.
    """
    from metatron.storage.memory_graph import link_memory_items_batch as _batch

    _batch(workspace_id, edges)


class Linker:
    """Counts related records and writes graph edges for a single target."""

    STAGE = "linker"

    def __init__(
        self,
        *,
        target: FreshnessTarget,
        freshness_store: FreshnessStore,
        coordination: CoordinationStore,
        threshold: float = 0.6,
        lock_ttl: int = 30,
        top_k: int = 20,
    ) -> None:
        self._target = target
        self._freshness_store = freshness_store
        self._coord = coordination
        self._threshold = threshold
        self._lock_ttl = lock_ttl
        self._top_k = top_k

    async def run(self, workspace_id: str, target_id: str) -> int:
        """Process a single record. Returns ``evidence_count``.

        Returns 0 and exits cleanly if: lock contended, record missing, or
        the similarity query produces no hits above threshold.
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
                "freshness.linker.lock_contended",
                workspace_id=workspace_id,
                target_id=target_id,
                target_kind=target_kind,
            )
            return 0

        started = time.monotonic()
        try:
            record = await self._target.get(workspace_id, target_id)
            if record is None:
                return 0

            hits = await self._target.similarity_search(
                workspace_id,
                record.content,
                top_k=self._top_k,
                agent_id=record.agent_id,
            )
            related: list[tuple[str, float]] = []
            for hit in hits:
                if not hit.target_id or hit.target_id == target_id:
                    continue
                if hit.score >= self._threshold:
                    related.append((hit.target_id, hit.score))

            evidence_count = len(related)
            await self._target.update_lifecycle(
                workspace_id,
                target_id,
                evidence_count=evidence_count,
            )

            if related:
                await self._target.link_edges_batch(
                    workspace_id,
                    target_id,
                    related,
                )

            await self._freshness_store.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_kind=target_kind,
                    target_id=target_id,
                    payload={
                        "stage": self.STAGE,
                        "evidence_count": evidence_count,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    },
                )
            )
            return evidence_count
        finally:
            await self._coord.release(self.STAGE, target_id, token, target_kind=target_kind)
