"""Unit tests for MTRNIX-316 worker hooks: heartbeat + reclaim + scheduled scan.

Covers:

* Startup path — tick_heartbeat, one-shot reclaim, optional legacy drain.
* Per-iteration — tick_heartbeat every iteration; reclaim every N iterations.
* Scheduled scan — runs when the timer fires (monkey-patched ``time.monotonic``).
* ``complete_job`` is called in the job finally, both on success and on error.
* Graceful shutdown — ``release_worker`` called on CancelledError.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob
from metatron.memory.freshness.worker import (
    FreshnessWorker,
    _Pipeline,
    _run_loop,
)


def _make_worker(**worker_kwargs: object) -> tuple[FreshnessWorker, AsyncMock, AsyncMock]:
    coordination = AsyncMock()
    freshness_pg = AsyncMock()
    decision_engine = AsyncMock()

    linker = AsyncMock()
    reconciler = AsyncMock()
    monitor = AsyncMock()
    curator = AsyncMock()
    target = MagicMock()
    target.kind = "memory_record"
    target.supports_candidate_promotion = True
    target.get = AsyncMock(return_value=None)

    pipelines = {
        "memory_record": _Pipeline(
            linker=linker,
            reconciler=reconciler,
            monitor=monitor,
            curator=curator,
            target=target,
        )
    }

    worker = FreshnessWorker(
        coordination=coordination,
        freshness_pg=freshness_pg,
        decision_engine=decision_engine,
        pipelines=pipelines,
        worker_id="test-worker-a",
        heartbeat_ttl=20,
        reclaim_interval_iterations=3,
        scheduled_scan_interval_seconds=60,
        **worker_kwargs,  # type: ignore[arg-type]
    )
    return worker, coordination, freshness_pg


def _job(ws: str, rid: str) -> FreshnessJob:
    return FreshnessJob(
        workspace_id=ws,
        event_type="knowledge_changed",
        target_kind="memory_record",
        target_id=rid,
    )


class TestHeartbeat:
    async def test_tick_heartbeat_every_iteration(self) -> None:
        worker, coord, _fp = _make_worker()
        coord.list_active_workspaces.return_value = []

        await worker.run_once(max_jobs=1)

        coord.tick_heartbeat.assert_awaited_with("test-worker-a", 20)


class TestReclaimPeriodicity:
    async def test_reclaim_runs_every_N_iterations(self) -> None:
        worker, coord, _fp = _make_worker()  # N=3
        coord.list_active_workspaces.return_value = []
        coord.list_processing_workers.return_value = []

        await worker.run_once(max_jobs=1)  # iter 1 → no reclaim
        await worker.run_once(max_jobs=1)  # iter 2 → no reclaim
        await worker.run_once(max_jobs=1)  # iter 3 → reclaim

        # Each iteration calls list_processing_workers via the reclaim helper.
        # With interval=3, only iteration 3 triggers it.
        assert coord.list_processing_workers.await_count == 1

    async def test_reclaim_skips_self(self) -> None:
        worker, coord, _fp = _make_worker()
        coord.list_active_workspaces.return_value = []
        coord.list_processing_workers.return_value = ["test-worker-a", "dead-peer"]
        coord.reclaim_worker_orphans.return_value = 2

        # Run 3 iterations so reclaim fires once.
        await worker.run_once(1)
        await worker.run_once(1)
        await worker.run_once(1)

        # Reclaim called only for the dead peer, never for self.
        coord.reclaim_worker_orphans.assert_awaited_once_with("dead-peer")


class TestCompleteJobFinally:
    async def test_complete_job_called_on_success(self) -> None:
        worker, coord, _fp = _make_worker()
        coord.list_active_workspaces.return_value = ["ws-A"]
        coord.dequeue_batch.return_value = [_job("ws-A", "rec-1")]

        await worker.run_once(max_jobs=5)

        coord.complete_job.assert_awaited_once()
        wid, job_arg = coord.complete_job.await_args.args
        assert wid == "test-worker-a"
        assert job_arg.target_id == "rec-1"

    async def test_complete_job_called_on_exception(self) -> None:
        worker, coord, _fp = _make_worker()
        coord.list_active_workspaces.return_value = ["ws-A"]
        coord.dequeue_batch.return_value = [_job("ws-A", "rec-1")]
        # Force a pipeline failure so _process_job raises.
        pipeline = worker._pipelines["memory_record"]
        pipeline.linker.run.side_effect = RuntimeError("kaboom")  # type: ignore[attr-defined]

        with pytest.raises(RuntimeError, match="kaboom"):
            await worker.run_once(max_jobs=5)

        # Even with the raise, complete_job still runs (outer finally).
        coord.complete_job.assert_awaited_once()


class TestScheduledScanTimer:
    async def test_scan_fires_when_due(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scanner = AsyncMock()
        worker, coord, _fp = _make_worker(scheduled_scanners=[scanner])
        coord.list_active_workspaces.return_value = []

        # First iteration initialises the timer — scan fires immediately
        # because _last_scan_monotonic defaults to 0.0 and elapsed > 60s
        # of fake-monotonic.
        monkeypatch.setattr(
            "metatron.memory.freshness.worker.time.monotonic",
            lambda: 100.0,
        )
        await worker.run_once(max_jobs=1)
        scanner.run.assert_awaited_once()

        # Next iteration a few seconds later — should NOT fire again.
        monkeypatch.setattr(
            "metatron.memory.freshness.worker.time.monotonic",
            lambda: 110.0,
        )
        await worker.run_once(max_jobs=1)
        assert scanner.run.await_count == 1

        # Iteration past the next interval — fires again.
        monkeypatch.setattr(
            "metatron.memory.freshness.worker.time.monotonic",
            lambda: 200.0,
        )
        await worker.run_once(max_jobs=1)
        assert scanner.run.await_count == 2


class TestGracefulShutdown:
    async def test_release_worker_on_cancel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``_run_loop`` is cancelled, ``release_worker`` runs in finally."""
        settings = get_settings()
        monkeypatch.setattr(settings, "freshness_enabled", True)
        monkeypatch.setattr(settings, "freshness_poll_seconds", 0.01)

        worker, coord, _fp = _make_worker()
        # Each run_once returns 0 processed → the loop sleeps.
        worker.run_once = AsyncMock(return_value=0)  # type: ignore[method-assign]

        task = asyncio.create_task(_run_loop(worker))
        # Let it tick once.
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        coord.release_worker.assert_awaited_with("test-worker-a")
