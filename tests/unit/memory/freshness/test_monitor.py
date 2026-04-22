"""Unit tests for FreshnessMonitor stage (MTRNIX-304, updated for MTRNIX-313).

Phase B rewires Monitor through :class:`MemoryTarget`. The age-gate added
in Phase B is KB-specific (``target_kind != "memory_record"``); memory
records preserve Phase A semantics where STALE fires on the first run
across the threshold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import LifecycleStatus, MemoryRecord, MemoryScope
from metatron.memory.freshness.monitor import FreshnessMonitor
from metatron.memory.freshness.target_memory import MemoryTarget


def _record(**overrides: object) -> MemoryRecord:
    now = datetime.now(UTC)
    defaults = {
        "id": "rec1",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "content": "content",
        "created_at": now - timedelta(days=10),
        "updated_at": now - timedelta(days=10),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _build_monitor(
    stale_days: int = 30,
) -> tuple[FreshnessMonitor, MagicMock, AsyncMock, AsyncMock]:
    pg = MagicMock()
    pg.get = AsyncMock()
    pg.update_lifecycle = AsyncMock()
    qdrant = MagicMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)
    coordination = AsyncMock()
    freshness_store = AsyncMock()
    monitor = FreshnessMonitor(
        target=target,
        freshness_store=freshness_store,
        coordination=coordination,
        stale_after_days=stale_days,
    )
    return monitor, pg, coordination, freshness_store


class TestMonitor:
    async def test_valid_until_expired_archives(self) -> None:
        monitor, pg, coord, _fs = _build_monitor()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(
            valid_until=datetime.now(UTC) - timedelta(days=1),
        )

        await monitor.run("ws1", "rec1")

        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["status"] == LifecycleStatus.ARCHIVED
        assert kwargs["freshness_score"] == 0.0

    async def test_superseded_by_present_marks_superseded(self) -> None:
        monitor, pg, coord, _fs = _build_monitor()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(superseded_by="rec-new")

        await monitor.run("ws1", "rec1")

        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["status"] == LifecycleStatus.SUPERSEDED
        assert kwargs["freshness_score"] == 0.1

    async def test_stale_threshold_marks_stale(self) -> None:
        monitor, pg, coord, _fs = _build_monitor(stale_days=5)
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(
            updated_at=datetime.now(UTC) - timedelta(days=10),
        )

        await monitor.run("ws1", "rec1")

        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["status"] == LifecycleStatus.STALE
        assert kwargs["freshness_score"] == 0.25

    async def test_fresh_record_not_updated(self) -> None:
        monitor, pg, coord, _fs = _build_monitor(stale_days=30)
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(
            updated_at=datetime.now(UTC) - timedelta(days=1),
        )

        await monitor.run("ws1", "rec1")

        pg.update_lifecycle.assert_not_awaited()

    async def test_valid_until_takes_priority_over_superseded(self) -> None:
        monitor, pg, coord, _fs = _build_monitor()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(
            valid_until=datetime.now(UTC) - timedelta(days=1),
            superseded_by="rec-new",
        )

        await monitor.run("ws1", "rec1")

        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["status"] == LifecycleStatus.ARCHIVED

    async def test_lock_contention_noop(self) -> None:
        monitor, pg, coord, _fs = _build_monitor()
        coord.acquire_lock.return_value = None

        await monitor.run("ws1", "rec1")

        pg.get.assert_not_awaited()
        pg.update_lifecycle.assert_not_awaited()
