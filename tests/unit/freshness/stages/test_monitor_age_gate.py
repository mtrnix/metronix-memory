"""Monitor age-gate — KB first-run stamps, memory first-run demotes (MTRNIX-313).

The age-gate added in Phase B prevents a bulk-STALE avalanche on first run
for KB raw_documents. Memory records (``target_kind == "memory_record"``)
preserve Phase A semantics: STALE fires immediately on first run across
the threshold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import LifecycleStatus
from metatron.freshness.stages.monitor import FreshnessMonitor
from metatron.freshness.targets import FreshnessTargetRecord


def _fake_target(record: FreshnessTargetRecord, *, kind: str) -> MagicMock:
    target = MagicMock()
    target.kind = kind
    target.supports_candidate_promotion = kind == "memory_record"
    target.get = AsyncMock(return_value=record)
    target.update_lifecycle = AsyncMock()
    target.sync_downstream_stores = AsyncMock()
    return target


def _stale_candidate() -> FreshnessTargetRecord:
    now = datetime.now(UTC)
    return FreshnessTargetRecord(
        target_id="t1",
        workspace_id="ws",
        content="old content",
        updated_at=now - timedelta(days=200),
        last_freshness_run_at=None,
    )


def _coord_granting() -> AsyncMock:
    coord = AsyncMock()
    coord.acquire_lock = AsyncMock(return_value="tok")
    coord.release = AsyncMock()
    return coord


async def test_kb_first_run_only_stamps_last_freshness_run_at() -> None:
    """KB target + never-seen-before → only stamp timestamp, no STALE."""
    record = _stale_candidate()
    target = _fake_target(record, kind="raw_document")
    coord = _coord_granting()
    monitor = FreshnessMonitor(
        target=target,
        freshness_store=AsyncMock(),
        coordination=coord,
        stale_after_days=30,
    )

    result = await monitor.run("ws", "t1")

    assert result is None
    target.update_lifecycle.assert_awaited_once()
    kwargs = target.update_lifecycle.await_args.kwargs
    # Only ``last_freshness_run_at`` is set — no status transition.
    assert "status" not in kwargs
    assert "last_freshness_run_at" in kwargs
    target.sync_downstream_stores.assert_not_awaited()


async def test_kb_second_run_applies_stale() -> None:
    """KB target + already stamped → STALE fires as expected."""
    now = datetime.now(UTC)
    record = FreshnessTargetRecord(
        target_id="t1",
        workspace_id="ws",
        content="old",
        updated_at=now - timedelta(days=200),
        last_freshness_run_at=now - timedelta(days=1),  # prior run
    )
    target = _fake_target(record, kind="raw_document")
    coord = _coord_granting()
    monitor = FreshnessMonitor(
        target=target,
        freshness_store=AsyncMock(),
        coordination=coord,
        stale_after_days=30,
    )

    result = await monitor.run("ws", "t1")

    assert result is LifecycleStatus.STALE
    kwargs = target.update_lifecycle.await_args.kwargs
    assert kwargs["status"] is LifecycleStatus.STALE
    assert kwargs["freshness_score"] == 0.25
    # Monitor mirrors status into derived stores on every transition.
    target.sync_downstream_stores.assert_awaited_once()


async def test_memory_first_run_applies_stale_without_age_gate() -> None:
    """Memory target preserves Phase A: STALE on first run across threshold."""
    record = _stale_candidate()
    target = _fake_target(record, kind="memory_record")
    coord = _coord_granting()
    monitor = FreshnessMonitor(
        target=target,
        freshness_store=AsyncMock(),
        coordination=coord,
        stale_after_days=30,
    )

    result = await monitor.run("ws", "t1")

    assert result is LifecycleStatus.STALE
    kwargs = target.update_lifecycle.await_args.kwargs
    assert kwargs["status"] is LifecycleStatus.STALE


async def test_no_rule_fires_is_noop_for_fresh_record() -> None:
    """A fresh record should not receive any update (preserves Phase A)."""
    now = datetime.now(UTC)
    record = FreshnessTargetRecord(
        target_id="t1",
        workspace_id="ws",
        content="recent",
        updated_at=now - timedelta(days=1),
    )
    target = _fake_target(record, kind="memory_record")
    coord = _coord_granting()
    monitor = FreshnessMonitor(
        target=target,
        freshness_store=AsyncMock(),
        coordination=coord,
        stale_after_days=30,
    )

    result = await monitor.run("ws", "t1")

    assert result is None
    target.update_lifecycle.assert_not_awaited()
