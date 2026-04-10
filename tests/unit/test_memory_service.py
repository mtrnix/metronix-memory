"""Tests for MemoryService (WS1 Stage 2 skeleton)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from metatron.agent.memory_service import MemoryService
from metatron.core.models import MemoryRecord, MemoryScope


def _make_service():
    """Create a MemoryService with mocked dependencies."""
    redis_cache = AsyncMock()
    return MemoryService(redis_cache=redis_cache), redis_cache


def _sample_record(**overrides) -> MemoryRecord:
    defaults = {
        "id": "mem001",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.SESSION,
        "session_id": "sess1",
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


# ---------------------------------------------------------------------------
# Session write-through
# ---------------------------------------------------------------------------


class TestCacheSession:
    async def test_writes_to_redis_and_neo4j(self) -> None:
        service, redis_cache = _make_service()
        record = _sample_record()
        redis_cache.cache.return_value = record

        with patch("metatron.agent.memory_service.save_memory_to_graph") as mock_graph:
            result = await service.cache_session("ws1", "sess1", record)

        assert result.id == "mem001"
        redis_cache.cache.assert_called_once_with(
            "ws1",
            "sess1",
            record,
            ttl_seconds=None,
        )
        mock_graph.assert_called_once_with(record)

    async def test_passes_ttl_override(self) -> None:
        service, redis_cache = _make_service()
        record = _sample_record()
        redis_cache.cache.return_value = record

        with patch("metatron.agent.memory_service.save_memory_to_graph"):
            await service.cache_session("ws1", "sess1", record, ttl_seconds=120)

        redis_cache.cache.assert_called_once_with(
            "ws1",
            "sess1",
            record,
            ttl_seconds=120,
        )

    async def test_neo4j_failure_does_not_block_cache(self) -> None:
        service, redis_cache = _make_service()
        record = _sample_record()
        redis_cache.cache.return_value = record

        with patch(
            "metatron.agent.memory_service.save_memory_to_graph",
            side_effect=Exception("neo4j down"),
        ):
            result = await service.cache_session("ws1", "sess1", record)

        # Should still succeed — Neo4j is best-effort
        assert result.id == "mem001"
        redis_cache.cache.assert_called_once()


# ---------------------------------------------------------------------------
# Session reads
# ---------------------------------------------------------------------------


class TestGetSession:
    async def test_returns_from_redis(self) -> None:
        service, redis_cache = _make_service()
        expected = _sample_record()
        redis_cache.get.return_value = expected

        result = await service.get_session("ws1", "sess1", "mem001")

        assert result is expected
        redis_cache.get.assert_called_once_with("ws1", "sess1", "mem001")

    async def test_returns_none_when_not_cached(self) -> None:
        service, redis_cache = _make_service()
        redis_cache.get.return_value = None

        result = await service.get_session("ws1", "sess1", "missing")

        assert result is None


class TestListSession:
    async def test_delegates_to_redis(self) -> None:
        service, redis_cache = _make_service()
        records = [_sample_record(id="m1"), _sample_record(id="m2")]
        redis_cache.list.return_value = records

        result = await service.list_session("ws1", "sess1")

        assert len(result) == 2
        redis_cache.list.assert_called_once_with("ws1", "sess1")


class TestInvalidateSession:
    async def test_delegates_to_redis(self) -> None:
        service, redis_cache = _make_service()
        redis_cache.invalidate.return_value = 3

        count = await service.invalidate_session("ws1", "sess1")

        assert count == 3
        redis_cache.invalidate.assert_called_once_with("ws1", "sess1")


class TestExtendSessionTtl:
    async def test_delegates_to_redis(self) -> None:
        service, redis_cache = _make_service()
        redis_cache.extend_ttl.return_value = True

        result = await service.extend_session_ttl("ws1", "sess1", 7200)

        assert result is True
        redis_cache.extend_ttl.assert_called_once_with("ws1", "sess1", 7200)


# ---------------------------------------------------------------------------
# Persistent memory stubs
# ---------------------------------------------------------------------------


class TestSave:
    async def test_raises_not_implemented(self) -> None:
        service, _ = _make_service()

        with pytest.raises(NotImplementedError):
            await service.save("ws1", _sample_record())


class TestPromote:
    async def test_raises_not_implemented(self) -> None:
        service, _ = _make_service()

        with pytest.raises(NotImplementedError):
            await service.promote("ws1", "sess1", "mem001")
