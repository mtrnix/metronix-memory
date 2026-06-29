"""Target adapter protocol for the freshness pipeline (MTRNIX-313, Phase B).

The pipeline stages are generic over the target kind. Concrete adapters live
elsewhere:

* :mod:`metronix.memory.freshness.target_memory` — ``MemoryTarget`` for agent memory.
* :mod:`metronix.ingestion.freshness.target_raw_document` — ``RawDocumentTarget``
  for KB.

The protocol is deliberately *not* in :mod:`metronix.core.interfaces` — that
would force enterprise coordination for every shape tweak. Promote later when
the shape has been stable across a release cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from metronix.core.models import LifecycleStatus

if TYPE_CHECKING:
    from datetime import datetime


@dataclass
class SimilarityHit:
    """One hit from a target-scoped similarity search.

    ``target_id`` is what the pipeline passes back into
    :meth:`FreshnessTarget.get` — for memory it is ``record.id``, for KB it
    is ``raw_documents.id`` (the doc_label in Qdrant payloads).
    """

    target_id: str
    score: float
    content: str = ""


@dataclass
class FreshnessTargetRecord:
    """Minimal shape the pipeline reads from a target.

    Adapters translate concrete store rows into this shape so stages do not
    need to know whether they are operating on a ``MemoryRecord`` or a
    ``RawDocument``.
    """

    target_id: str
    workspace_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    status: LifecycleStatus = LifecycleStatus.ACTIVE
    freshness_score: float = 0.5
    superseded_by: str | None = None
    valid_until: datetime | None = None
    updated_at: datetime | None = None
    evidence_count: int = 0
    verification_state: str | None = None
    last_freshness_run_at: datetime | None = None
    # ``agent_id`` is memory-specific but small enough to keep here so the
    # generic Linker/Reconciler can still pass it through to the adapter's
    # similarity_search when present. KB adapters leave it empty.
    agent_id: str | None = None


@runtime_checkable
class FreshnessTarget(Protocol):
    """Adapter binding a pipeline stage to a concrete target store.

    Every method is async and NEVER raises — best-effort semantics apply to
    the graph-side writes (``link_edges_batch``, ``alias_edge``,
    ``sync_downstream_stores``). PG lifecycle writes may raise on a real
    engine failure; callers typically let those surface so the worker can
    record them as errors.
    """

    kind: str  # "memory_record" | "raw_document"
    supports_candidate_promotion: bool  # True for memory, False for KB in Phase B

    async def get(self, workspace_id: str, target_id: str) -> FreshnessTargetRecord | None: ...

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
    ) -> None: ...

    async def similarity_search(
        self,
        workspace_id: str,
        content: str,
        *,
        top_k: int,
        agent_id: str | None = None,
    ) -> list[SimilarityHit]: ...

    async def link_edges_batch(
        self,
        workspace_id: str,
        source_id: str,
        edges: list[tuple[str, float]],
    ) -> None:
        """Best-effort. NEVER raises."""

    async def alias_edge(
        self,
        workspace_id: str,
        source_id: str,
        target_id: str,
    ) -> None:
        """Best-effort. NEVER raises."""

    async def sync_downstream_stores(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus,
        freshness_score: float,
    ) -> None:
        """Called after lifecycle status changes.

        Memory target is a no-op today. KB target mirrors the PG row into
        Qdrant chunk payloads and Neo4j ``:Document`` properties. Best-effort,
        NEVER raises.
        """

    async def list_stale_candidates(
        self,
        workspace_id: str,
        *,
        older_than: datetime,
        limit: int,
    ) -> list[str]:
        """Return up to ``limit`` target_ids whose freshness clock expired.

        Used by the scheduled-scan safety net (MTRNIX-316) to enqueue
        records that never received a write-triggered freshness event.
        Concrete adapters override this; KB's default (see
        :class:`RawDocumentTarget`) returns an empty list so KB-side
        scheduled scan stays opt-in for a future ticket. Memory's
        implementation delegates to ``MemoryPostgresStore.list_stale_candidates``.
        """
        return []


__all__ = [
    "FreshnessTarget",
    "FreshnessTargetRecord",
    "SimilarityHit",
]
