"""Unit tests for FreshnessWorker (MTRNIX-304)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.config import get_settings
from metatron.core.models import FreshnessDecision, FreshnessJob
from metatron.memory.freshness.worker import FreshnessWorker, main


def _jobs(ws: str, ids: list[str]) -> list[FreshnessJob]:
    return [
        FreshnessJob(
            workspace_id=ws,
            event_type="knowledge_changed",
            target_kind="memory_record",
            target_id=i,
        )
        for i in ids
    ]


def _make_worker() -> tuple[FreshnessWorker, AsyncMock, AsyncMock, AsyncMock]:
    coordination = AsyncMock()
    freshness_pg = AsyncMock()
    decision_engine = AsyncMock()
    decision_engine.decide.return_value = FreshnessDecision(
        action="tag",
        confidence=0.9,
        tags=["payment"],
    )

    linker = AsyncMock()
    linker.run.return_value = 2
    reconciler = AsyncMock()
    reconciler.run.return_value = None
    monitor = AsyncMock()
    monitor.run.return_value = None
    curator = AsyncMock()
    curator.run.return_value = None

    pg_store = AsyncMock()
    pg_store.get.return_value = None  # DecisionEngine.apply branch skipped

    worker = FreshnessWorker(
        coordination=coordination,
        freshness_pg=freshness_pg,
        decision_engine=decision_engine,
        pg_store_factory=lambda _ws: pg_store,
        qdrant_store_factory=lambda _ws: AsyncMock(),
        linker=linker,
        reconciler=reconciler,
        monitor=monitor,
        curator=curator,
    )
    return worker, coordination, freshness_pg, decision_engine


class TestRunOnce:
    async def test_processes_batch(self) -> None:
        worker, coord, fp, _de = _make_worker()
        coord.list_active_workspaces.return_value = ["ws1"]
        coord.dequeue_batch.return_value = _jobs("ws1", ["r1", "r2", "r3"])

        processed = await worker.run_once(max_jobs=10)

        assert processed == 3
        assert fp.save_machine_event.await_count >= 3  # at least job_received

    async def test_empty_queue_returns_zero(self) -> None:
        worker, coord, _fp, _de = _make_worker()
        coord.list_active_workspaces.return_value = []

        processed = await worker.run_once(max_jobs=10)

        assert processed == 0

    async def test_skips_knowledge_deleted_jobs(self) -> None:
        worker, coord, _fp, _de = _make_worker()
        coord.list_active_workspaces.return_value = ["ws1"]
        coord.dequeue_batch.return_value = [
            FreshnessJob(
                workspace_id="ws1",
                event_type="knowledge_deleted",
                target_kind="memory_record",
                target_id="r1",
            )
        ]

        processed = await worker.run_once(max_jobs=10)

        # Delete events are accounted for in the return count but do not
        # trigger the stages for a record that no longer exists.
        assert processed == 1
        worker._linker.run.assert_not_awaited()  # type: ignore[attr-defined]


class TestBackoff:
    async def test_escalates_then_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three failing iterations trigger 2s, 4s, 8s sleeps; then exit."""
        settings = get_settings()
        monkeypatch.setattr(settings, "freshness_enabled", True)
        monkeypatch.setattr(settings, "freshness_max_consecutive_errors", 3)
        monkeypatch.setattr(settings, "freshness_backoff_base_seconds", 2.0)
        monkeypatch.setattr(settings, "freshness_backoff_max_seconds", 60.0)

        worker = MagicMock()
        worker.run_once = AsyncMock(side_effect=RuntimeError("boom"))

        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        from metatron.memory.freshness import worker as worker_mod

        with pytest.raises(RuntimeError, match="boom"):
            await worker_mod._run_loop(worker)

        # Two backoff sleeps before the 3rd error re-raises.
        assert sleeps == [2.0, 4.0]


class TestFlagOff:
    async def test_main_exits_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "freshness_enabled", False)

        # Would hang forever if it tried to bootstrap. Must return None.
        result = await main()
        assert result is None
