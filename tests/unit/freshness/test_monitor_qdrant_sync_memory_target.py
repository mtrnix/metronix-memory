"""FreshnessMonitor + MemoryTarget Qdrant sync regression tests (MTRNIX-322).

MTRNIX-313 wired ``sync_downstream_stores`` into ``FreshnessMonitor.run``
after every lifecycle transition, but the memory adapter implementation
was a deliberate no-op. MTRNIX-322 makes the memory adapter write the
Qdrant ``status`` payload. These tests pin that behaviour against the
real ``MemoryTarget`` (not a mocked target) so a future refactor cannot
accidentally sever the wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import LifecycleStatus, MemoryRecord, MemoryScope
from metatron.freshness.stages.monitor import FreshnessMonitor
from metatron.memory.freshness.target_memory import MemoryTarget


def _record(**overrides: object) -> MemoryRecord:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
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
    qdrant = AsyncMock()
    qdrant.update_payload = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)
    coordination = AsyncMock()
    freshness_store = AsyncMock()
    monitor = FreshnessMonitor(
        target=target,
        freshness_store=freshness_store,
        coordination=coordination,
        stale_after_days=stale_days,
    )
    return monitor, pg, qdrant, freshness_store


async def test_archived_transition_syncs_qdrant_status() -> None:
    monitor, pg, qdrant, freshness_store = _build_monitor()
    monitor._coord.acquire_lock = AsyncMock(return_value="tok")  # type: ignore[attr-defined]
    monitor._coord.release = AsyncMock()  # type: ignore[attr-defined]
    pg.get.return_value = _record(
        valid_until=datetime.now(UTC) - timedelta(days=1),
    )

    await monitor.run("ws1", "rec1")

    qdrant.update_payload.assert_awaited_once_with("rec1", {"status": "archived"})
    freshness_store.save_machine_event.assert_awaited_once()


async def test_superseded_transition_syncs_qdrant_status() -> None:
    monitor, pg, qdrant, freshness_store = _build_monitor()
    monitor._coord.acquire_lock = AsyncMock(return_value="tok")  # type: ignore[attr-defined]
    monitor._coord.release = AsyncMock()  # type: ignore[attr-defined]
    pg.get.return_value = _record(superseded_by="rec-new")

    await monitor.run("ws1", "rec1")

    qdrant.update_payload.assert_awaited_once_with("rec1", {"status": "superseded"})
    freshness_store.save_machine_event.assert_awaited_once()


async def test_stale_transition_syncs_qdrant_status() -> None:
    monitor, pg, qdrant, freshness_store = _build_monitor(stale_days=5)
    monitor._coord.acquire_lock = AsyncMock(return_value="tok")  # type: ignore[attr-defined]
    monitor._coord.release = AsyncMock()  # type: ignore[attr-defined]
    pg.get.return_value = _record(
        updated_at=datetime.now(UTC) - timedelta(days=10),
    )

    await monitor.run("ws1", "rec1")

    qdrant.update_payload.assert_awaited_once_with("rec1", {"status": "stale"})
    freshness_store.save_machine_event.assert_awaited_once()


async def test_fresh_record_skips_qdrant_sync() -> None:
    monitor, pg, qdrant, freshness_store = _build_monitor(stale_days=30)
    monitor._coord.acquire_lock = AsyncMock(return_value="tok")  # type: ignore[attr-defined]
    monitor._coord.release = AsyncMock()  # type: ignore[attr-defined]
    pg.get.return_value = _record(
        updated_at=datetime.now(UTC) - timedelta(days=1),
    )

    await monitor.run("ws1", "rec1")

    qdrant.update_payload.assert_not_awaited()
    freshness_store.save_machine_event.assert_not_awaited()


async def test_qdrant_failure_does_not_abort_monitor() -> None:
    """Best-effort semantics — worker loop stays alive on Qdrant failure."""
    monitor, pg, qdrant, freshness_store = _build_monitor()
    monitor._coord.acquire_lock = AsyncMock(return_value="tok")  # type: ignore[attr-defined]
    monitor._coord.release = AsyncMock()  # type: ignore[attr-defined]
    pg.get.return_value = _record(
        valid_until=datetime.now(UTC) - timedelta(days=1),
    )
    qdrant.update_payload.side_effect = RuntimeError("qdrant down")

    # Must not raise.
    new_status = await monitor.run("ws1", "rec1")

    assert new_status is LifecycleStatus.ARCHIVED
    pg.update_lifecycle.assert_awaited_once()
    freshness_store.save_machine_event.assert_awaited_once()
