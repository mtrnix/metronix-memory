"""Redis async client — cache backend for Metatron.

Thin wrapper around redis.asyncio. Provides connection lifecycle,
health check, and basic cache operations. Also exposes queue + lock
primitives used by the freshness pipeline (MTRNIX-304). No business logic.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import structlog
from redis.asyncio import Redis

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = structlog.get_logger()


# Lua scripts keep lock operations atomic so we cannot release or refresh
# a lock held by another worker (the classic "release someone else's lock"
# bug). Tokens are unique per acquisition (uuid4 hex).
_RELEASE_LOCK_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

_HEARTBEAT_LOCK_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
"""

# Atomic multi-pop (RPOP count). Fallback to pipelined RPOP is implemented
# in Python in case redis-py's `rpop` count mode is unavailable.
_RPOP_BATCH_LUA = """
local out = {}
for i = 1, tonumber(ARGV[1]) do
    local v = redis.call("RPOP", KEYS[1])
    if v == false then
        break
    end
    out[#out + 1] = v
end
return out
"""


class RedisStore:
    """Async Redis client for caching + freshness coordination."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Redis = Redis.from_url(  # type: ignore[type-arg]
            url,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    @property
    def client(self) -> Redis:  # type: ignore[type-arg]
        """Expose the underlying client for advanced callers (tests)."""
        return self._client

    async def ping(self) -> bool:
        """Check connectivity. Returns True if Redis responds."""
        try:
            return bool(await self._client.ping())
        except Exception:
            logger.warning("redis_ping_failed", url=self._url)
            return False

    async def get(self, key: str) -> str | None:
        """Get a value by key."""
        return await self._client.get(key)  # type: ignore[return-value]

    async def set(self, key: str, value: str | bytes, ttl: int | None = None) -> None:
        """Set a value with optional TTL in seconds."""
        if ttl is not None:
            await self._client.set(key, value, ex=ttl)
        else:
            await self._client.set(key, value)

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys. Returns number of keys removed."""
        return await self._client.delete(*keys)  # type: ignore[return-value]

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        return bool(await self._client.exists(key))

    async def expire(self, key: str, ttl: int) -> bool:
        """Set TTL on an existing key."""
        return bool(await self._client.expire(key, ttl))

    async def get_json(self, key: str) -> Any | None:
        """Get and deserialize a JSON value."""
        raw = await self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)  # type: ignore[arg-type]

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Serialize value as JSON and store."""
        await self.set(key, json.dumps(value, default=str), ttl=ttl)

    # ------------------------------------------------------------------
    # Queue primitives (MTRNIX-304)
    # ------------------------------------------------------------------

    async def lpush(self, key: str, value: str) -> int:
        """Push a value to the head of a list. Returns new length."""
        awaitable = cast("Awaitable[int]", self._client.lpush(key, value))
        return int(await awaitable)

    async def rpop_batch(self, key: str, max_items: int) -> list[str]:
        """Pop up to ``max_items`` values from the tail of a list atomically.

        Uses a Lua script so the batch is atomic — two workers polling the
        same queue cannot observe the same job.
        """
        if max_items <= 0:
            return []
        awaitable = cast(
            "Awaitable[list[str] | None]",
            self._client.eval(_RPOP_BATCH_LUA, 1, key, str(max_items)),
        )
        raw = await awaitable
        return list(raw or [])

    async def llen(self, key: str) -> int:
        """Length of a Redis list. 0 if missing."""
        awaitable = cast("Awaitable[int]", self._client.llen(key))
        return int(await awaitable)

    async def scan_keys(self, match: str, count: int = 100) -> list[str]:
        """Non-blocking SCAN over keys matching a pattern.

        Returns a full list — callers are expected to scope ``match`` to a
        workspace prefix so the enumeration stays bounded.
        """
        cursor = 0
        out: list[str] = []
        while True:
            awaitable = cast(
                "Awaitable[tuple[int, list[str]]]",
                self._client.scan(cursor=cursor, match=match, count=count),
            )
            cursor, chunk = await awaitable
            out.extend(chunk)
            if cursor == 0:
                break
        return out

    # ------------------------------------------------------------------
    # Lock primitives (MTRNIX-304)
    # ------------------------------------------------------------------

    async def acquire_lock(self, key: str, ttl_seconds: int, token: str) -> bool:
        """``SET key token NX EX ttl`` — returns True if acquired."""
        result = await self._client.set(
            key,
            token,
            nx=True,
            ex=ttl_seconds,
        )
        return bool(result)

    async def heartbeat_lock(self, key: str, ttl_seconds: int, token: str) -> bool:
        """Extend a lock's TTL — only if this worker still owns the token."""
        awaitable = cast(
            "Awaitable[int]",
            self._client.eval(
                _HEARTBEAT_LOCK_LUA,
                1,
                key,
                token,
                str(ttl_seconds * 1000),
            ),
        )
        return bool(await awaitable)

    async def release_lock(self, key: str, token: str) -> bool:
        """Release a lock — only if this worker still owns the token."""
        awaitable = cast(
            "Awaitable[int]",
            self._client.eval(_RELEASE_LOCK_LUA, 1, key, token),
        )
        return bool(await awaitable)

    async def close(self) -> None:
        """Close the connection pool."""
        await self._client.aclose()
        logger.info("redis_closed")
