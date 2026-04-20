"""Unit tests for CoordinationStore (MTRNIX-304).

Mocks the underlying RedisStore so no live Redis is required. Asserts
keyspace convention, JSON boundary, and per-stage-per-item lock semantics.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from metatron.core.models import FreshnessJob
from metatron.memory.freshness.coordination import (
    CoordinationStore,
    queue_key_for,
)


def _make() -> tuple[CoordinationStore, AsyncMock]:
    redis = AsyncMock()
    return CoordinationStore(redis=redis), redis


class TestQueueKeys:
    def test_queue_key_includes_workspace(self) -> None:
        assert queue_key_for("ws1") == "freshness:queue:ws1"


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
        assert key == "freshness:queue:ws1"
        assert '"event_type"' in payload
        assert '"rec1"' in payload


class TestDequeue:
    async def test_dequeue_batch_returns_parsed_jobs(self) -> None:
        store, redis = _make()
        redis.rpop_batch.return_value = [
            '{"workspace_id":"ws1","event_type":"knowledge_changed",'
            '"target_kind":"memory_record","target_id":"rec1","payload":{}}',
            '{"workspace_id":"ws1","event_type":"content_changed",'
            '"target_kind":"memory_record","target_id":"rec2","payload":{"k":"v"}}',
        ]

        jobs = await store.dequeue_batch("ws1", max_items=5)

        assert len(jobs) == 2
        assert jobs[0].target_id == "rec1"
        assert jobs[1].event_type == "content_changed"
        assert jobs[1].payload == {"k": "v"}
        redis.rpop_batch.assert_awaited_once_with("freshness:queue:ws1", 5)

    async def test_dequeue_batch_skips_malformed_entries(self) -> None:
        store, redis = _make()
        redis.rpop_batch.return_value = [
            "not-json",
            '{"workspace_id":"ws1","event_type":"knowledge_changed",'
            '"target_kind":"memory_record","target_id":"rec1","payload":{}}',
        ]

        jobs = await store.dequeue_batch("ws1", max_items=5)

        # Malformed entries must be dropped, not raised — the worker cannot
        # afford a poison message to stall the queue.
        assert len(jobs) == 1
        assert jobs[0].target_id == "rec1"

    async def test_queue_depth_delegates_to_llen(self) -> None:
        store, redis = _make()
        redis.llen.return_value = 42

        depth = await store.queue_depth("ws1")

        assert depth == 42
        redis.llen.assert_awaited_once_with("freshness:queue:ws1")

    async def test_list_active_workspaces_parses_keys(self) -> None:
        store, redis = _make()
        redis.scan_keys.return_value = [
            "freshness:queue:ws1",
            "freshness:queue:ws2",
        ]

        ws = await store.list_active_workspaces()

        assert sorted(ws) == ["ws1", "ws2"]
        redis.scan_keys.assert_awaited_once_with("freshness:queue:*")


class TestLocks:
    async def test_acquire_lock_returns_token_on_success(self) -> None:
        store, redis = _make()
        redis.acquire_lock.return_value = True

        token = await store.acquire_lock("linker", "rec1", ttl=30)

        assert token is not None
        redis.acquire_lock.assert_awaited_once()
        key, ttl, tok = redis.acquire_lock.await_args.args
        assert key == "freshness:linker:rec1"
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
        redis.heartbeat_lock.assert_awaited_once_with("freshness:linker:rec1", 30, "tok")

    async def test_release_uses_token_guard(self) -> None:
        store, redis = _make()
        redis.release_lock.return_value = True

        await store.release("linker", "rec1", token="tok")

        redis.release_lock.assert_awaited_once_with("freshness:linker:rec1", "tok")


class TestCheckpoints:
    async def test_write_checkpoint_uses_stage_namespace(self) -> None:
        store, redis = _make()

        await store.write_checkpoint("linker", "rec1", "clean")

        redis.write_checkpoint.assert_awaited_once()
        key, value = redis.write_checkpoint.await_args.args[:2]
        assert key == "freshness:checkpoint:linker:rec1"
        assert value == "clean"

    async def test_read_checkpoint_returns_value(self) -> None:
        store, redis = _make()
        redis.read_checkpoint.return_value = "clean"

        v = await store.read_checkpoint("linker", "rec1")

        assert v == "clean"
        redis.read_checkpoint.assert_awaited_once_with("freshness:checkpoint:linker:rec1")
