"""Unit tests for RedisStore LMOVE-family primitives (PROJ-316).

Covers ``lmove_rightleft`` (the RPOPLPUSH-style primitive used by the
freshness processing-list reclaim pattern), ``peek_tail`` (LINDEX key -1),
and ``lrem`` (remove a serialised job by value on successful processing).

Uses ``AsyncMock`` so no live Redis is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from metronix.storage.redis import RedisStore


def _make_store() -> tuple[RedisStore, AsyncMock]:
    store = RedisStore("redis://localhost:6379/0")
    fake = AsyncMock()
    store._client = fake  # type: ignore[assignment]
    return store, fake


class TestLmoveRightLeft:
    async def test_returns_moved_value(self) -> None:
        store, client = _make_store()
        client.lmove.return_value = "a"

        out = await store.lmove_rightleft("queue", "processing")

        assert out == "a"
        client.lmove.assert_awaited_once_with("queue", "processing", "RIGHT", "LEFT")

    async def test_returns_none_when_source_empty(self) -> None:
        store, client = _make_store()
        client.lmove.return_value = None

        out = await store.lmove_rightleft("queue", "processing")

        assert out is None


class TestPeekTail:
    async def test_returns_tail_value(self) -> None:
        store, client = _make_store()
        client.lindex.return_value = "tail-value"

        out = await store.peek_tail("queue")

        assert out == "tail-value"
        client.lindex.assert_awaited_once_with("queue", -1)

    async def test_returns_none_on_missing_key(self) -> None:
        store, client = _make_store()
        client.lindex.return_value = None

        out = await store.peek_tail("missing")

        assert out is None


class TestLrem:
    async def test_lrem_default_count_is_one(self) -> None:
        store, client = _make_store()
        client.lrem.return_value = 1

        n = await store.lrem("processing", "job-json")

        assert n == 1
        client.lrem.assert_awaited_once_with("processing", 1, "job-json")

    async def test_lrem_explicit_count(self) -> None:
        store, client = _make_store()
        client.lrem.return_value = 2

        n = await store.lrem("processing", "job-json", count=2)

        assert n == 2
        client.lrem.assert_awaited_once_with("processing", 2, "job-json")

    async def test_lrem_returns_zero_when_no_match(self) -> None:
        store, client = _make_store()
        client.lrem.return_value = 0

        n = await store.lrem("processing", "nonexistent")

        assert n == 0
