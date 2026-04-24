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

    async def test_stops_early_when_queue_drained(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

    async def test_returns_empty_on_redis_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.scan_keys.side_effect = RuntimeError("redis down")

        # Graceful degradation: reclaim pass sees no workers and retries later.
        assert await store.list_processing_workers() == []


class TestReclaimWorkerOrphans:
    async def test_happy_path_drains_processing_list_into_queue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.exists.return_value = False  # worker dead
        redis.acquire_lock.return_value = True
        payloads = [
            _serialise("ws-A", "rec-1"),
            _serialise("ws-A", "rec-2"),
            _serialise("ws-B", "rec-3"),
        ]
        # peek_tail returns the next item to move; LMOVE moves and returns it.
        # After 3 successful moves, peek_tail returns None.
        redis.peek_tail.side_effect = [*payloads, None]
        redis.lmove_rightleft.side_effect = payloads

        n = await store.reclaim_worker_orphans("dead-worker")

        assert n == 3
        # Verify the jobs were routed to correct workspace queues.
        lmove_args = [c.args for c in redis.lmove_rightleft.await_args_list]
        assert lmove_args[0] == (
            "freshness:development:processing:dead-worker",
            "freshness:development:queue:ws-A",
        )
        assert lmove_args[1] == (
            "freshness:development:processing:dead-worker",
            "freshness:development:queue:ws-A",
        )
        assert lmove_args[2] == (
            "freshness:development:processing:dead-worker",
            "freshness:development:queue:ws-B",
        )
        redis.release_lock.assert_awaited_once()

    async def test_skips_live_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.exists.return_value = True  # worker alive

        n = await store.reclaim_worker_orphans("live-worker")

        assert n == 0
        redis.acquire_lock.assert_not_called()
        redis.lmove_rightleft.assert_not_called()

    async def test_lock_busy_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.exists.return_value = False
        redis.acquire_lock.return_value = False  # someone else holds the lock

        n = await store.reclaim_worker_orphans("dead-worker")

        assert n == 0
        redis.peek_tail.assert_not_called()
        redis.lmove_rightleft.assert_not_called()

    async def test_race_lmove_returns_none_exits_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.exists.return_value = False
        redis.acquire_lock.return_value = True
        # peek_tail sees a job, but LMOVE races and returns None (someone
        # else removed the tail). Loop exits cleanly.
        redis.peek_tail.return_value = _serialise("ws-A", "rec-1")
        redis.lmove_rightleft.return_value = None

        n = await store.reclaim_worker_orphans("dead-worker")

        assert n == 0
        redis.release_lock.assert_awaited_once()

    async def test_poison_entry_is_lrem_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.exists.return_value = False
        redis.acquire_lock.return_value = True
        redis.peek_tail.side_effect = ["not-json", _serialise("ws-A", "rec-1"), None]
        redis.lmove_rightleft.side_effect = [_serialise("ws-A", "rec-1")]

        n = await store.reclaim_worker_orphans("dead-worker")

        # Poison entry doesn't count as recovered, but next iteration moves
        # the valid one.
        assert n == 1
        # LREM called on the poison entry.
        redis.lrem.assert_awaited_once()
        assert redis.lrem.await_args.args[1] == "not-json"


class TestDrainLegacyUnprefixed:
    async def test_drains_legacy_into_prefixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        redis.scan_keys.return_value = ["freshness:queue:ws-A", "freshness:queue:ws-B"]
        # Each legacy key has 2 items; LMOVE returns them in order then None.
        redis.lmove_rightleft.side_effect = [
            "job1",
            "job2",
            None,  # ws-A drained
            "job3",
            "job4",
            None,  # ws-B drained
        ]

        moved = await store.drain_legacy_unprefixed()

        assert moved == 4
        redis.scan_keys.assert_awaited_once_with("freshness:queue:*")
        # Verify LMOVE from legacy → prefixed keys.
        lmove_args = [c.args for c in redis.lmove_rightleft.await_args_list]
        assert lmove_args[0] == (
            "freshness:queue:ws-A",
            "freshness:development:queue:ws-A",
        )
        assert lmove_args[3] == (
            "freshness:queue:ws-B",
            "freshness:development:queue:ws-B",
        )

    async def test_noop_when_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from metatron.freshness import coordination as coord_mod

        monkeypatch.setattr(coord_mod, "get_settings", lambda: _FakeSettings(env=""))
        store, redis = _make()

        moved = await store.drain_legacy_unprefixed()

        assert moved == 0
        redis.scan_keys.assert_not_called()

    async def test_filters_env_prefixed_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key like ``freshness:development:queue:ws-A`` is NOT legacy
        and must not be re-drained into itself."""
        monkeypatch.setenv("METATRON_ENV", "development")
        store, redis = _make()
        # Only the "freshness:queue:ws-A" (count=2 colons) is legacy; the
        # prefixed one has count=4 and is filtered out.
        redis.scan_keys.return_value = [
            "freshness:queue:ws-A",
            "freshness:development:queue:ws-B",
        ]
        redis.lmove_rightleft.side_effect = ["job1", None]

        moved = await store.drain_legacy_unprefixed()

        assert moved == 1
        # Only one source key processed.
        lmove_args = [c.args for c in redis.lmove_rightleft.await_args_list]
        assert all(src == "freshness:queue:ws-A" for src, _dst in lmove_args)


class _FakeSettings:
    def __init__(self, env: str) -> None:
        self.env = env
