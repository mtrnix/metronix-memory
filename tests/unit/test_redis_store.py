"""Tests for RedisStore."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from metatron.storage.redis import RedisStore


def _make_store() -> RedisStore:
    """Create a RedisStore with a mocked client."""
    store = RedisStore("redis://localhost:6379/0")
    store._client = AsyncMock()
    return store


class TestPing:
    async def test_ping_success(self):
        store = _make_store()
        store._client.ping.return_value = True
        assert await store.ping() is True

    async def test_ping_failure_returns_false(self):
        store = _make_store()
        store._client.ping.side_effect = ConnectionError("refused")
        assert await store.ping() is False


class TestGetSet:
    async def test_set_without_ttl(self):
        store = _make_store()
        await store.set("k", "v")
        store._client.set.assert_called_once_with("k", "v")

    async def test_set_with_ttl(self):
        store = _make_store()
        await store.set("k", "v", ttl=60)
        store._client.set.assert_called_once_with("k", "v", ex=60)

    async def test_get_returns_value(self):
        store = _make_store()
        store._client.get.return_value = "hello"
        assert await store.get("k") == "hello"

    async def test_get_returns_none_on_miss(self):
        store = _make_store()
        store._client.get.return_value = None
        assert await store.get("k") is None


class TestDelete:
    async def test_delete_returns_count(self):
        store = _make_store()
        store._client.delete.return_value = 2
        assert await store.delete("a", "b") == 2

    async def test_delete_single_key(self):
        store = _make_store()
        store._client.delete.return_value = 1
        assert await store.delete("a") == 1
        store._client.delete.assert_called_once_with("a")


class TestExists:
    async def test_exists_true(self):
        store = _make_store()
        store._client.exists.return_value = 1
        assert await store.exists("k") is True

    async def test_exists_false(self):
        store = _make_store()
        store._client.exists.return_value = 0
        assert await store.exists("k") is False


class TestExpire:
    async def test_expire_success(self):
        store = _make_store()
        store._client.expire.return_value = True
        assert await store.expire("k", 300) is True


class TestJson:
    async def test_set_json_and_get_json(self):
        store = _make_store()
        store._client.get.return_value = '{"a": 1}'

        result = await store.get_json("k")
        assert result == {"a": 1}

    async def test_set_json_serializes(self):
        store = _make_store()
        await store.set_json("k", {"a": 1}, ttl=30)
        store._client.set.assert_called_once_with("k", '{"a": 1}', ex=30)

    async def test_get_json_returns_none_on_miss(self):
        store = _make_store()
        store._client.get.return_value = None
        assert await store.get_json("k") is None


class TestClose:
    async def test_close_calls_aclose(self):
        store = _make_store()
        await store.close()
        store._client.aclose.assert_called_once()
