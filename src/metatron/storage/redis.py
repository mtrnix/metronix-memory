"""Redis async client — cache backend for Metatron.

Thin wrapper around redis.asyncio. Provides connection lifecycle,
health check, and basic cache operations. No business logic.
"""

from __future__ import annotations

from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()


class RedisStore:
    """Async Redis client for caching."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Redis = Redis.from_url(  # type: ignore[type-arg]
            url,
            decode_responses=True,
            socket_connect_timeout=5,
        )

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

    async def set(
        self, key: str, value: str | bytes, ttl: int | None = None
    ) -> None:
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
        import json

        raw = await self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)  # type: ignore[arg-type]

    async def set_json(
        self, key: str, value: Any, ttl: int | None = None
    ) -> None:
        """Serialize value as JSON and store."""
        import json

        await self.set(key, json.dumps(value, default=str), ttl=ttl)

    async def close(self) -> None:
        """Close the connection pool."""
        await self._client.aclose()
        logger.info("redis_closed")
