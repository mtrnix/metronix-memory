"""Unit tests for processing-list dequeue + complete (MTRNIX-316).

Exercises the ``dequeue_batch`` rework (LMOVE per item into the per-worker
processing list), ``complete_job`` (LREM on success), and
``list_processing_workers`` (SCAN over ``freshness:{env}:processing:*``).

Reclaim + legacy-drain tests are added in Task 6.
"""

from __future__ import annotations

import json
import warnings
from unittest.mock import AsyncMock

import pytest

from metatron.core import config as config_mod
from metatron.core.models import FreshnessJob
from metatron.freshness.coordination import CoordinationStore


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    config_mod._settings = None
    yield
    config_mod._settings = None


def _make() -> tuple[CoordinationStore, AsyncMock]:
    redis = AsyncMock()
    return CoordinationStore(redis=redis), redis


def _serialise(ws: str, tid: str) -> str:
    return json.dumps(
        {
            "workspace_id": ws,
            "event_type": "knowledge_changed",
            "target_kind": "memory_record",
            "target_id": tid,
            "payload": {},
        },
        sort_keys=True,
    )


class TestDequeueBatch:
    async def test_dequeues_via_lmove_into_processing_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.lmove_rightleft.side_effect = [
            _serialise("ws-A", "rec-1"),
            _serialise("ws-A", "rec-2"),
            None,  # queue drained
        ]

        jobs = await store.dequeue_batch("ws-A", 5, worker_id="w1")

        assert len(jobs) == 2
        assert [j.target_id for j in jobs] == ["rec-1", "rec-2"]
        # Three LMOVE calls (2 successful + 1 terminating None).
        assert redis.lmove_rightleft.await_count == 3
        # Each call moves from the workspace queue into the per-worker list.
        args_list = [c.args for c in redis.lmove_rightleft.await_args_list]
        assert all(
            a == ("freshness:development:queue:ws-A", "freshness:development:processing:w1")
            for a in args_list
        )

    async def test_stops_early_when_queue_drained(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.lmove_rightleft.side_effect = [None]

        jobs = await store.dequeue_batch("ws-A", 20, worker_id="w1")

        assert jobs == []
        # Should stop after first None, not try all 20.
        assert redis.lmove_rightleft.await_count == 1

    async def test_skips_poison_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.lmove_rightleft.side_effect = [
            "not-json",
            _serialise("ws-A", "rec-2"),
            None,
        ]

        jobs = await store.dequeue_batch("ws-A", 5, worker_id="w1")

        # Poison entries are dropped (not raised); LMOVE already committed them
        # to the processing list. A later ``complete_job`` is not called for
        # them — they are cleaned up by the reclaim pass's poison branch.
        assert len(jobs) == 1
        assert jobs[0].target_id == "rec-2"

    async def test_deprecation_shim_without_worker_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Phase A tests still pass ``dequeue_batch(ws, N)``. Shim keeps them green.

        Emits a DeprecationWarning and synthesises an internal worker id.
        """
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.lmove_rightleft.side_effect = [None]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            jobs = await store.dequeue_batch("ws-A", 5)  # type: ignore[call-arg]
            assert any(issubclass(w.category, DeprecationWarning) for w in caught)

        assert jobs == []


class TestCompleteJob:
    async def test_lrem_removes_job_from_processing_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.lrem.return_value = 1

        job = FreshnessJob(
            workspace_id="ws-A",
            event_type="knowledge_changed",
            target_kind="memory_record",
            target_id="rec-1",
            payload={},
        )
        await store.complete_job("w1", job)

        redis.lrem.assert_awaited_once()
        key, serialised = redis.lrem.await_args.args[:2]
        assert key == "freshness:development:processing:w1"
        # serialised shape includes all expected fields
        assert '"target_id": "rec-1"' in serialised
        assert redis.lrem.await_args.kwargs.get("count", 1) == 1

    async def test_swallows_redis_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.lrem.side_effect = RuntimeError("redis down")

        job = FreshnessJob(
            workspace_id="ws-A",
            event_type="knowledge_changed",
            target_kind="memory_record",
            target_id="rec-1",
            payload={},
        )
        # Worker's finally block relies on complete_job not raising.
        await store.complete_job("w1", job)


class TestListProcessingWorkers:
    async def test_scans_and_strips_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.scan_keys.return_value = [
            "freshness:development:processing:worker-a",
            "freshness:development:processing:worker-b",
        ]

        out = await store.list_processing_workers()

        assert sorted(out) == ["worker-a", "worker-b"]
        redis.scan_keys.assert_awaited_once_with("freshness:development:processing:*")

    async def test_returns_empty_on_redis_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.scan_keys.side_effect = RuntimeError("redis down")

        # Graceful degradation: reclaim pass sees no workers and retries later.
        assert await store.list_processing_workers() == []
