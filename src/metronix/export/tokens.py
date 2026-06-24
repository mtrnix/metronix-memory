from __future__ import annotations

import json
import secrets
from typing import Any, Protocol


class _RedisLike(Protocol):
    async def set(self, key: str, value: str | bytes, ttl: int | None = None) -> None:
        """Set ``key`` to ``value`` with an optional TTL in seconds."""

    async def get(self, key: str) -> str | None:
        """Return the value for ``key`` or ``None`` if absent."""

    async def getdel(self, key: str) -> str | None:
        """Atomically return and delete the value for ``key`` (Redis GETDEL)."""


def _key(token: str) -> str:
    return f"export_token:{token}"


def _parse(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class ExportTokenStore:
    def __init__(self, redis: _RedisLike, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def mint(self, export_id: str, path: str) -> str:
        token = secrets.token_urlsafe(32)
        payload = json.dumps({"export_id": export_id, "path": path})
        await self._redis.set(_key(token), payload, ttl=self._ttl)
        return token

    async def peek(self, token: str) -> dict[str, Any] | None:
        """Non-destructive read — lets the caller validate before consuming."""
        return _parse(await self._redis.get(_key(token)))

    async def consume(self, token: str) -> dict[str, Any] | None:
        """Atomically read-and-delete the token (one-time semantics).

        Uses Redis GETDEL so two concurrent downloads of the same token can't both
        succeed — exactly one gets the payload, the other gets ``None``.
        """
        return _parse(await self._redis.getdel(_key(token)))
