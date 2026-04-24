"""MemoryTarget.sync_downstream_stores tests (MTRNIX-322).

Covers the Qdrant status payload mirroring introduced in MTRNIX-322:

* Happy path: ``qdrant.update_payload`` is called with
  ``{"status": status.value}`` only (``freshness_score`` is intentionally
  dropped — see adapter docstring).
* Failure path: ``update_payload`` raising any ``Exception`` must be
  swallowed (PG remains source of truth) and the
  ``freshness_qdrant_sync_failed_total`` counter incremented exactly once.
* Happy path does not touch the counter.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from metatron.core.models import LifecycleStatus
from metatron.freshness import metrics as freshness_metrics
from metatron.memory.freshness.target_memory import MemoryTarget


async def test_sync_downstream_writes_status_only_on_happy_path() -> None:
    pg = MagicMock()
    qdrant = AsyncMock()
    qdrant.update_payload = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)

    await target.sync_downstream_stores(
        "ws",
        "rec_abc",
        status=LifecycleStatus.STALE,
        freshness_score=0.25,
    )

    qdrant.update_payload.assert_awaited_once_with("rec_abc", {"status": "stale"})


async def test_sync_downstream_swallows_qdrant_errors() -> None:
    pg = MagicMock()
    qdrant = AsyncMock()
    qdrant.update_payload = AsyncMock(side_effect=RuntimeError("qdrant down"))
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)

    # Must not raise.
    await target.sync_downstream_stores(
        "ws",
        "rec_abc",
        status=LifecycleStatus.ARCHIVED,
        freshness_score=0.0,
    )


async def test_sync_downstream_increments_counter_on_failure() -> None:
    pg = MagicMock()
    qdrant = AsyncMock()
    qdrant.update_payload = AsyncMock(side_effect=RuntimeError("qdrant down"))
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)

    mock_counter = MagicMock()
    # ``.labels(...)`` returns a child metric; we then call ``.inc()`` on it.
    mock_counter.labels.return_value = mock_counter
    with patch.object(freshness_metrics, "qdrant_sync_failed", mock_counter):
        await target.sync_downstream_stores(
            "ws",
            "rec_abc",
            status=LifecycleStatus.ARCHIVED,
            freshness_score=0.0,
        )

    mock_counter.labels.assert_called_once_with(
        target_kind="memory_record",
        stage="sync_downstream",
    )
    mock_counter.inc.assert_called_once()


async def test_sync_downstream_does_not_increment_counter_on_success() -> None:
    pg = MagicMock()
    qdrant = AsyncMock()
    qdrant.update_payload = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)

    mock_counter = MagicMock()
    mock_counter.labels.return_value = mock_counter
    with patch.object(freshness_metrics, "qdrant_sync_failed", mock_counter):
        await target.sync_downstream_stores(
            "ws",
            "rec_abc",
            status=LifecycleStatus.ACTIVE,
            freshness_score=0.5,
        )

    mock_counter.labels.assert_not_called()
    mock_counter.inc.assert_not_called()


async def test_sync_downstream_swallows_resolver_errors() -> None:
    """Even the factory raising (e.g. misconfigured Qdrant client) must not leak."""
    pg = MagicMock()

    def _broken_factory(_ws: str) -> object:
        raise RuntimeError("qdrant client unavailable")

    target = MemoryTarget(pg_store=pg, qdrant_store_factory=_broken_factory)

    mock_counter = MagicMock()
    mock_counter.labels.return_value = mock_counter
    with patch.object(freshness_metrics, "qdrant_sync_failed", mock_counter):
        # Must not raise.
        await target.sync_downstream_stores(
            "ws",
            "rec_abc",
            status=LifecycleStatus.SUPERSEDED,
            freshness_score=0.1,
        )

    mock_counter.inc.assert_called_once()


async def test_sync_downstream_still_survives_when_metrics_break() -> None:
    """Metrics must never bite — even if ``.labels(...).inc()`` raises."""
    pg = MagicMock()
    qdrant = AsyncMock()
    qdrant.update_payload = AsyncMock(side_effect=RuntimeError("qdrant down"))
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)

    mock_counter = MagicMock()
    mock_counter.labels.side_effect = RuntimeError("metrics registry broken")
    with patch.object(freshness_metrics, "qdrant_sync_failed", mock_counter):
        # Must not raise.
        await target.sync_downstream_stores(
            "ws",
            "rec_abc",
            status=LifecycleStatus.STALE,
            freshness_score=0.25,
        )
