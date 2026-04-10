"""Tests for RedisSessionCache (WS1 Stage 2)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.storage.memory_redis import (
    RedisSessionCache,
    _deserialize_record,
    _serialize_record,
)
from metatron.storage.redis import RedisStore


def _make_cache(ttl: int = 3600) -> RedisSessionCache:
    """Create a RedisSessionCache with a mocked RedisStore."""
    store = RedisStore("redis://localhost:6379/0")
    store._client = AsyncMock()
    return RedisSessionCache(store, default_ttl=ttl)


def _sample_record(**overrides) -> MemoryRecord:
    defaults = {
        "id": "mem001",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.SESSION,
        "source_type": "conversation",
        "content": "hello",
        "session_id": "sess1",
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _record_json(record: MemoryRecord) -> str:
    return _serialize_record(record)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip(self) -> None:
        record = _sample_record(tags=["pref"], importance_score=0.8)
        raw = _serialize_record(record)
        restored = _deserialize_record(raw)

        assert restored.id == record.id
        assert restored.scope == MemoryScope.SESSION
        assert restored.tags == ["pref"]
        assert restored.importance_score == 0.8
        assert restored.content == "hello"

    def test_none_ttl_survives_roundtrip(self) -> None:
        record = _sample_record(ttl_expires_at=None)
        restored = _deserialize_record(_serialize_record(record))
        assert restored.ttl_expires_at is None


# ---------------------------------------------------------------------------
# Task 1: cache + get
# ---------------------------------------------------------------------------


class TestCache:
    async def test_stores_record_with_default_ttl(self) -> None:
        cache = _make_cache(ttl=600)
        record = _sample_record()
        cache._store._client.get.return_value = None  # no existing index

        result = await cache.cache("ws1", "sess1", record)

        assert result.id == "mem001"
        # Record key + index key = 2 set calls
        assert cache._store._client.set.call_count == 2
        # First call: record with TTL
        rec_call = cache._store._client.set.call_args_list[0]
        assert rec_call.args[0] == "mem:ws1:sess1:mem001"
        assert rec_call.kwargs.get("ex") == 600

    async def test_ttl_override(self) -> None:
        cache = _make_cache(ttl=600)
        record = _sample_record()
        cache._store._client.get.return_value = None

        await cache.cache("ws1", "sess1", record, ttl_seconds=120)

        rec_call = cache._store._client.set.call_args_list[0]
        assert rec_call.kwargs.get("ex") == 120

    async def test_appends_to_existing_index(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = '["existing001"]'
        record = _sample_record(id="mem002")

        await cache.cache("ws1", "sess1", record)

        # Index should now have both IDs
        idx_call = cache._store._client.set.call_args_list[1]
        stored_ids = json.loads(idx_call.args[1])
        assert "existing001" in stored_ids
        assert "mem002" in stored_ids

    async def test_does_not_duplicate_in_index(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = '["mem001"]'
        record = _sample_record(id="mem001")

        await cache.cache("ws1", "sess1", record)

        idx_call = cache._store._client.set.call_args_list[1]
        stored_ids = json.loads(idx_call.args[1])
        assert stored_ids.count("mem001") == 1


class TestGet:
    async def test_returns_record_when_found(self) -> None:
        cache = _make_cache()
        record = _sample_record()
        cache._store._client.get.return_value = _record_json(record)

        result = await cache.get("ws1", "sess1", "mem001")

        assert result is not None
        assert result.id == "mem001"
        assert result.content == "hello"
        cache._store._client.get.assert_called_with("mem:ws1:sess1:mem001")

    async def test_returns_none_when_not_found(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = None

        result = await cache.get("ws1", "sess1", "nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# Task 2: list, invalidate, extend_ttl
# ---------------------------------------------------------------------------


class TestList:
    async def test_returns_all_session_records(self) -> None:
        cache = _make_cache()
        r1 = _sample_record(id="mem001", content="first")
        r2 = _sample_record(id="mem002", content="second")
        cache._store._client.get.side_effect = [
            '["mem001", "mem002"]',  # index
            _record_json(r1),
            _record_json(r2),
        ]

        results = await cache.list("ws1", "sess1")

        assert len(results) == 2
        assert results[0].id == "mem001"
        assert results[1].id == "mem002"

    async def test_returns_empty_when_no_index(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = None

        results = await cache.list("ws1", "sess1")

        assert results == []

    async def test_skips_expired_records(self) -> None:
        cache = _make_cache()
        r1 = _sample_record(id="mem001", content="alive")
        cache._store._client.get.side_effect = [
            '["mem001", "mem002"]',  # index
            _record_json(r1),
            None,  # mem002 expired
        ]

        results = await cache.list("ws1", "sess1")

        assert len(results) == 1
        assert results[0].id == "mem001"


class TestInvalidate:
    async def test_deletes_all_session_keys(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = '["mem001", "mem002"]'
        cache._store._client.delete.return_value = 3

        count = await cache.invalidate("ws1", "sess1")

        assert count == 2  # number of records, not keys
        cache._store._client.delete.assert_called_once()
        deleted_keys = cache._store._client.delete.call_args.args
        assert len(deleted_keys) == 3  # 2 records + 1 index
        assert "mem:ws1:sess1:mem001" in deleted_keys
        assert "mem:ws1:sess1:mem002" in deleted_keys
        assert "mem:ws1:sess1:_index" in deleted_keys

    async def test_returns_zero_when_no_session(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = None

        count = await cache.invalidate("ws1", "sess1")

        assert count == 0


class TestExtendTtl:
    async def test_extends_all_keys(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = '["mem001", "mem002"]'
        cache._store._client.expire.return_value = True

        result = await cache.extend_ttl("ws1", "sess1", 7200)

        assert result is True
        # 2 record keys + 1 index key = 3 expire calls
        assert cache._store._client.expire.call_count == 3

    async def test_returns_false_when_no_session(self) -> None:
        cache = _make_cache()
        cache._store._client.get.return_value = None

        result = await cache.extend_ttl("ws1", "sess1", 7200)

        assert result is False
