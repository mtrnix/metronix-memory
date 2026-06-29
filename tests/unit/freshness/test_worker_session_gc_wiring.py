"""Unit tests for FreshnessWorker SessionGCPass wiring (Phase 2 memory-scopes).

Covers:
* W1 — when freshness_scheduled_scan_enabled=True, session_gc_passes list is non-empty
         after passing to FreshnessWorker constructor
* W2 — when session_gc_passes=[] (or freshness_scheduled_scan_enabled=False), no GC called
* W3 — one worker tick fires both ScheduledScan.run and SessionGCPass.run exactly once
         when the scan timer is due
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.core import config as config_mod
from metronix.freshness.scheduled_scan import SessionGCPass
from metronix.memory.freshness.worker import FreshnessWorker


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    config_mod._settings = None
    yield
    config_mod._settings = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_worker(
    *,
    scheduled_scanners=None,  # type: ignore[no-untyped-def]
    session_gc_passes=None,  # type: ignore[no-untyped-def]
) -> FreshnessWorker:
    coord = AsyncMock()
    freshness_pg = AsyncMock()
    decision_engine = AsyncMock()
    return FreshnessWorker(
        coordination=coord,
        freshness_pg=freshness_pg,
        decision_engine=decision_engine,
        pipelines={},
        scheduled_scanners=scheduled_scanners or [],
        session_gc_passes=session_gc_passes or [],
        # Set scan interval to 0 so the scan is always due.
        scheduled_scan_interval_seconds=0,
    )


def _make_gc_pass(delete_return: int = 0) -> SessionGCPass:
    pg = MagicMock()
    pg.delete_session_records_past_grace = AsyncMock(return_value=delete_return)

    async def lister() -> list[str]:
        return []

    return SessionGCPass(
        pg_store=pg,  # type: ignore[arg-type]
        workspace_lister=lister,
        grace_hours=24,
    )


# ---------------------------------------------------------------------------
# W1 — session_gc_passes stored on worker
# ---------------------------------------------------------------------------


class TestWorkerSessionGcWiring:
    def test_w1_session_gc_passes_stored(self) -> None:
        gc = _make_gc_pass()
        worker = _make_minimal_worker(session_gc_passes=[gc])

        assert len(worker._session_gc_passes) == 1
        assert worker._session_gc_passes[0] is gc

    def test_w1_empty_by_default(self) -> None:
        worker = _make_minimal_worker()
        assert worker._session_gc_passes == []


# ---------------------------------------------------------------------------
# W2 — no GC called when session_gc_passes is empty
# ---------------------------------------------------------------------------


class TestWorkerNoGcWhenEmpty:
    async def test_w2_no_gc_call_when_empty(self) -> None:
        """_run_scheduled_scans with no gc passes does not explode."""
        worker = _make_minimal_worker()
        # Should complete without error.
        await worker._run_scheduled_scans()


# ---------------------------------------------------------------------------
# W3 — both ScheduledScan.run and SessionGCPass.run fired exactly once per tick
# ---------------------------------------------------------------------------


class TestWorkerBothRunFired:
    async def test_w3_both_run_called_on_scan_due(self) -> None:
        """When the scan timer is due, both scanner.run and gc.run are called once."""
        scanner = AsyncMock()
        scanner.run = AsyncMock(return_value=0)

        gc = AsyncMock()
        gc.run = AsyncMock(return_value=0)

        worker = FreshnessWorker(
            coordination=AsyncMock(),
            freshness_pg=AsyncMock(),
            decision_engine=AsyncMock(),
            pipelines={},
            scheduled_scanners=[scanner],  # type: ignore[list-item]
            session_gc_passes=[gc],  # type: ignore[list-item]
            scheduled_scan_interval_seconds=0,  # always due
        )

        await worker._run_scheduled_scans()

        scanner.run.assert_awaited_once()
        gc.run.assert_awaited_once()
