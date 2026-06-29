"""Unit tests for CoordinationStore (MTRNIX-304).

Mocks the underlying RedisStore so no live Redis is required. Asserts
keyspace convention, JSON boundary, and per-stage-per-item lock semantics.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from metronix.core.models import FreshnessJob
from metronix.memory.freshness.coordination import (
    CoordinationStore,
    queue_key_for,
)


def _make() -> tuple[CoordinationStore, AsyncMock]:
    redis = AsyncMock()
    return CoordinationStore(redis=redis), redis


class TestQueueKeys:
    def test_queue_key_includes_workspace(self) -> None:
        assert queue_key_for("ws1") == "freshness:development:queue:ws1"


class TestEnqueue:
    async def test_enqueue_serializes_to_json_and_lpushes(self) -> None:
        store, redis = _make()
        job = FreshnessJob(
            workspace_id="ws1",
            event_type="knowledge_changed",
            target_kind="memory_record",
            target_id="rec1",
            payload={"source": "test"},
        )

        await store.enqueue_job(job)

        redis.lpush.assert_awaited_once()
        key, payload = redis.lpush.await_args.args
        assert key == "freshness:development:queue:ws1"
        assert '"event_type"' in payload
        assert '"rec1"' in payload


class TestDequeue:
    async def test_dequeue_batch_returns_parsed_jobs(self) -> None:
        store, redis = _make()
        # MTRNIX-316: dequeue now loops LMOVE per item; mock returns items
        # until None terminates the loop.
        redis.lmove_rightleft.side_effect = [
            '{"workspace_id":"ws1","event_type":"knowledge_changed",'
            '"target_kind":"memory_record","target_id":"rec1","payload":{}}',
            '{"workspace_id":"ws1","event_type":"content_changed",'
            '"target_kind":"memory_record","target_id":"rec2","payload":{"k":"v"}}',
            None,
        ]

        jobs = await store.dequeue_batch("ws1", max_items=5, worker_id="w1")

        assert len(jobs) == 2
        assert jobs[0].target_id == "rec1"
        assert jobs[1].event_type == "content_changed"
        assert jobs[1].payload == {"k": "v"}
        # Each call moves from the workspace queue to the worker's processing list.
        first_call = redis.lmove_rightleft.await_args_list[0].args
        assert first_call == (
            "freshness:development:queue:ws1",
            "freshness:development:processing:w1",
        )

    async def test_dequeue_batch_skips_malformed_entries(self) -> None:
        store, redis = _make()
        redis.lmove_rightleft.side_effect = [
            "not-json",
            '{"workspace_id":"ws1","event_type":"knowledge_changed",'
            '"target_kind":"memory_record","target_id":"rec1","payload":{}}',
            None,
        ]

        jobs = await store.dequeue_batch("ws1", max_items=5, worker_id="w1")

        # Malformed entries must be dropped, not raised — the worker cannot
        # afford a poison message to stall the queue.
        assert len(jobs) == 1
        assert jobs[0].target_id == "rec1"

    async def test_queue_depth_delegates_to_llen(self) -> None:
        store, redis = _make()
        redis.llen.return_value = 42

        depth = await store.queue_depth("ws1")

        assert depth == 42
        redis.llen.assert_awaited_once_with("freshness:development:queue:ws1")

    async def test_list_active_workspaces_parses_keys(self) -> None:
        store, redis = _make()
        redis.scan_keys.return_value = [
            "freshness:development:queue:ws1",
            "freshness:development:queue:ws2",
        ]

        ws = await store.list_active_workspaces()

        assert sorted(ws) == ["ws1", "ws2"]
        redis.scan_keys.assert_awaited_once_with("freshness:development:queue:*")


class TestLocks:
    async def test_acquire_lock_returns_token_on_success(self) -> None:
        store, redis = _make()
        redis.acquire_lock.return_value = True

        token = await store.acquire_lock("linker", "rec1", ttl=30)

        assert token is not None
        redis.acquire_lock.assert_awaited_once()
        key, ttl, tok = redis.acquire_lock.await_args.args
        assert key == "freshness:development:linker:rec1"
        assert ttl == 30
        assert tok == token

    async def test_acquire_lock_returns_none_on_contention(self) -> None:
        store, redis = _make()
        redis.acquire_lock.return_value = False

        token = await store.acquire_lock("linker", "rec1", ttl=30)

        assert token is None

    async def test_heartbeat_with_token_extends_lock(self) -> None:
        store, redis = _make()
        redis.heartbeat_lock.return_value = True

        ok = await store.heartbeat("linker", "rec1", ttl=30, token="tok")

        assert ok is True
        redis.heartbeat_lock.assert_awaited_once_with(
            "freshness:development:linker:rec1", 30, "tok"
        )

    async def test_release_uses_token_guard(self) -> None:
        store, redis = _make()
        redis.release_lock.return_value = True

        await store.release("linker", "rec1", token="tok")

        redis.release_lock.assert_awaited_once_with("freshness:development:linker:rec1", "tok")


class TestCheckpointsRemoved:
    """Checkpoint mechanism was removed — stages are idempotent without it."""

    def test_coordination_store_has_no_checkpoint_methods(self) -> None:
        store, _redis = _make()
        assert not hasattr(store, "write_checkpoint")
        assert not hasattr(store, "read_checkpoint")
