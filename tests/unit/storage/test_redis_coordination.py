"""Unit tests for RedisStore freshness primitives (MTRNIX-304).

Uses ``AsyncMock`` on the underlying ``redis.asyncio.Redis`` client — no
live Redis required. Asserts the command sequence and Lua argument shapes
so the token-guarded scripts cannot regress to "release someone else's
lock".
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from metatron.storage.redis import RedisStore


def _make_store() -> tuple[RedisStore, AsyncMock]:
    store = RedisStore("redis://localhost:6379/0")
    fake = AsyncMock()
    store._client = fake  # type: ignore[assignment]
    return store, fake


class TestQueuePrimitives:
    async def test_lpush_returns_length(self) -> None:
        store, client = _make_store()
        client.lpush.return_value = 3

        length = await store.lpush("freshness:queue:ws1", "payload")

        assert length == 3
        client.lpush.assert_awaited_once_with("freshness:queue:ws1", "payload")

    async def test_rpop_batch_zero_returns_empty(self) -> None:
        store, client = _make_store()

        result = await store.rpop_batch("freshness:queue:ws1", 0)

        assert result == []
        client.eval.assert_not_called()

    async def test_rpop_batch_calls_lua_script(self) -> None:
        store, client = _make_store()
        client.eval.return_value = ["job1", "job2"]

        out = await store.rpop_batch("freshness:queue:ws1", 5)

        assert out == ["job1", "job2"]
        args = client.eval.await_args.args
        assert args[1] == 1  # numkeys
        assert args[2] == "freshness:queue:ws1"
        assert args[3] == "5"

    async def test_rpop_batch_handles_none_response(self) -> None:
        store, client = _make_store()
        client.eval.return_value = None

        out = await store.rpop_batch("freshness:queue:ws1", 5)

        assert out == []

    async def test_llen_returns_int(self) -> None:
        store, client = _make_store()
        client.llen.return_value = 7

        n = await store.llen("freshness:queue:ws1")

        assert n == 7

    async def test_scan_keys_iterates_cursor(self) -> None:
        store, client = _make_store()
        client.scan.side_effect = [
            (42, ["freshness:queue:ws1", "freshness:queue:ws2"]),
            (0, ["freshness:queue:ws3"]),
        ]

        keys = await store.scan_keys("freshness:queue:*")

        assert keys == [
            "freshness:queue:ws1",
            "freshness:queue:ws2",
            "freshness:queue:ws3",
        ]
        assert client.scan.await_count == 2


class TestLockPrimitives:
    async def test_acquire_lock_true_when_set_succeeds(self) -> None:
        store, client = _make_store()
        client.set.return_value = True

        ok = await store.acquire_lock("freshness:linker:rec1", 30, "tok")

        assert ok is True
        client.set.assert_awaited_once_with("freshness:linker:rec1", "tok", nx=True, ex=30)

    async def test_acquire_lock_false_when_already_held(self) -> None:
        store, client = _make_store()
        client.set.return_value = None

        ok = await store.acquire_lock("freshness:linker:rec1", 30, "tok")

        assert ok is False

    async def test_release_lock_uses_token_guard(self) -> None:
        store, client = _make_store()
        client.eval.return_value = 1

        ok = await store.release_lock("freshness:linker:rec1", "tok-a")

        assert ok is True
        args = client.eval.await_args.args
        # Token passed as ARGV so Lua can compare.
        assert args[3] == "tok-a"

    async def test_release_lock_refuses_mismatched_token(self) -> None:
        store, client = _make_store()
        client.eval.return_value = 0

        ok = await store.release_lock("freshness:linker:rec1", "foreign")

        assert ok is False

    async def test_heartbeat_lock_encodes_ttl_as_ms(self) -> None:
        store, client = _make_store()
        client.eval.return_value = 1

        ok = await store.heartbeat_lock("freshness:linker:rec1", 30, "tok")

        assert ok is True
        args = client.eval.await_args.args
        # TTL seconds → milliseconds for PEXPIRE.
        assert args[4] == "30000"


class TestCheckpoints:
    async def test_write_checkpoint_uses_ttl(self) -> None:
        store, client = _make_store()

        await store.write_checkpoint("freshness:checkpoint:linker:rec1", "clean", ttl=600)

        client.set.assert_awaited_once_with("freshness:checkpoint:linker:rec1", "clean", ex=600)

    async def test_read_checkpoint_missing_returns_none(self) -> None:
        store, client = _make_store()
        client.get.return_value = None

        val = await store.read_checkpoint("freshness:checkpoint:linker:rec1")

        assert val is None

    async def test_read_checkpoint_returns_value(self) -> None:
        store, client = _make_store()
        client.get.return_value = "clean"

        val = await store.read_checkpoint("freshness:checkpoint:linker:rec1")

        assert val == "clean"
