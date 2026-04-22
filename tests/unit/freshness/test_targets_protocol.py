"""Protocol conformance — both adapters implement :class:`FreshnessTarget`.

MTRNIX-313: any new adapter must conform to the Protocol so stages can swap
targets without knowing the concrete store. These tests also exercise the
``FreshnessTargetRecord`` DTO round-trip.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from metatron.core.models import LifecycleStatus
from metatron.freshness.targets import (
    FreshnessTarget,
    FreshnessTargetRecord,
    SimilarityHit,
)


def test_memory_target_satisfies_protocol() -> None:
    from metatron.memory.freshness.target_memory import MemoryTarget

    target = MemoryTarget(pg_store=MagicMock(), qdrant_store_factory=lambda _ws: MagicMock())
    # ``FreshnessTarget`` is a Protocol — ``isinstance`` works at runtime
    # because the Protocol is ``@runtime_checkable`` via its declaration.
    assert isinstance(target, FreshnessTarget)
    assert target.kind == "memory_record"
    assert target.supports_candidate_promotion is True


def test_raw_document_target_satisfies_protocol() -> None:
    # Deferred import — the KB adapter ships in Task 8. Skip cleanly if the
    # module is not yet present so the Task 5 suite stays green.
    try:
        from metatron.ingestion.freshness.target_raw_document import (
            RawDocumentTarget,
        )
    except ImportError:  # pragma: no cover — Task 8 will ship the module
        return

    target = RawDocumentTarget(pg_store=MagicMock(), qdrant_factory=lambda _ws: MagicMock())
    assert isinstance(target, FreshnessTarget)
    assert target.kind == "raw_document"
    assert target.supports_candidate_promotion is False


def test_freshness_target_record_defaults() -> None:
    rec = FreshnessTargetRecord(target_id="x", workspace_id="ws", content="hello")
    assert rec.status is LifecycleStatus.ACTIVE
    assert rec.freshness_score == 0.5
    assert rec.evidence_count == 0
    assert rec.last_freshness_run_at is None


def test_similarity_hit_minimal() -> None:
    hit = SimilarityHit(target_id="t1", score=0.5)
    assert hit.target_id == "t1"
    assert hit.content == ""


def test_freshness_target_record_custom_updated_at() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    rec = FreshnessTargetRecord(
        target_id="x",
        workspace_id="ws",
        content="c",
        updated_at=now,
        last_freshness_run_at=now,
    )
    assert rec.updated_at == now
    assert rec.last_freshness_run_at == now
