"""Redis session cache for Agent Memory (WS1).

Provides TTL-bound session memory storage using the existing RedisStore.
Each session's records are stored as individual JSON keys with an index key
tracking all record IDs in the session.

This is an L1 storage module — no business logic, no cross-store awareness.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from metronix.core.models import MemoryRecord, MemoryScope

if TYPE_CHECKING:
    from metronix.storage.redis import RedisStore

logger = structlog.get_logger()

# Key patterns:
#   mem:{workspace_id}:{session_id}:{record_id}  — individual record (JSON)
#   mem:{workspace_id}:{session_id}:_index        — list of record IDs (JSON)

_PREFIX = "mem"


def _record_key(workspace_id: str, session_id: str, record_id: str) -> str:
    return f"{_PREFIX}:{workspace_id}:{session_id}:{record_id}"


def _index_key(workspace_id: str, session_id: str) -> str:
    return f"{_PREFIX}:{workspace_id}:{session_id}:_index"


def _serialize_record(record: MemoryRecord) -> str:
    d = asdict(record)
    d["scope"] = record.scope.value
    return json.dumps(d, default=str)


def _deserialize_record(raw: str) -> MemoryRecord:
    d = json.loads(raw)
    d["scope"] = MemoryScope(d["scope"])
    if d.get("ttl_expires_at"):
        d["ttl_expires_at"] = datetime.fromisoformat(d["ttl_expires_at"])
    else:
        d["ttl_expires_at"] = None
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    return MemoryRecord(**d)


class RedisSessionCache:
    """TTL-bound session memory cache backed by Redis.

    Stores MemoryRecord objects as JSON with automatic expiration.
    Does NOT implement SessionMemoryInterface directly — the full
    interface (including promote) lives in MemoryService (L4).
    """

    def __init__(self, store: RedisStore, default_ttl: int = 14400) -> None:
        self._store = store
        self._default_ttl = default_ttl

    async def cache(
        self,
        workspace_id: str,
        session_id: str,
        record: MemoryRecord,
        *,
        ttl_seconds: int | None = None,
    ) -> MemoryRecord:
        """Store a record in session cache with TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        rkey = _record_key(workspace_id, session_id, record.id)
        ikey = _index_key(workspace_id, session_id)

        # Write record
        await self._store.set(rkey, _serialize_record(record), ttl=ttl)

        # Update index — append record ID.
        # Note: read-modify-write is not atomic. Safe for single-agent sessions;
        # for concurrent writes, migrate to Redis SET (SADD) in the future.
        raw_index = await self._store.get(ikey)
        ids: list[str] = json.loads(raw_index) if raw_index else []
        if record.id not in ids:
            ids.append(record.id)
        await self._store.set(ikey, json.dumps(ids), ttl=ttl)

        logger.debug(
            "memory_redis.cached",
            record_id=record.id,
            session_id=session_id,
            ttl=ttl,
        )
        return record

    async def get(
        self,
        workspace_id: str,
        session_id: str,
        record_id: str,
    ) -> MemoryRecord | None:
        """Fetch a single record from session cache."""
        rkey = _record_key(workspace_id, session_id, record_id)
        raw = await self._store.get(rkey)
        if raw is None:
            return None
        return _deserialize_record(raw)

    async def list(
        self,
        workspace_id: str,
        session_id: str,
    ) -> list[MemoryRecord]:
        """List all records for a session. Skips expired (missing) records."""
        ikey = _index_key(workspace_id, session_id)
        raw_index = await self._store.get(ikey)
        if raw_index is None:
            return []

        ids: list[str] = json.loads(raw_index)
        records: list[MemoryRecord] = []
        for record_id in ids:
            rkey = _record_key(workspace_id, session_id, record_id)
            raw = await self._store.get(rkey)
            if raw is not None:
                records.append(_deserialize_record(raw))
        return records

    async def invalidate(self, workspace_id: str, session_id: str) -> int:
        """Drop all records for a session. Returns number of records removed."""
        ikey = _index_key(workspace_id, session_id)
        raw_index = await self._store.get(ikey)
        if raw_index is None:
            return 0

        ids: list[str] = json.loads(raw_index)
        keys_to_delete = [_record_key(workspace_id, session_id, rid) for rid in ids]
        keys_to_delete.append(ikey)
        await self._store.delete(*keys_to_delete)

        logger.debug(
            "memory_redis.invalidated",
            session_id=session_id,
            count=len(ids),
        )
        return len(ids)

    async def delete_record(
        self,
        workspace_id: str,
        session_id: str,
        record_id: str,
    ) -> bool:
        """Delete a single record from session cache and remove from index.

        Returns True if the record key existed.
        """
        rkey = _record_key(workspace_id, session_id, record_id)
        ikey = _index_key(workspace_id, session_id)

        deleted = await self._store.delete(rkey)

        # Update index — remove record ID
        raw_index = await self._store.get(ikey)
        if raw_index is not None:
            ids: list[str] = json.loads(raw_index)
            if record_id in ids:
                ids.remove(record_id)
                if ids:
                    await self._store.set(ikey, json.dumps(ids))
                else:
                    await self._store.delete(ikey)

        return deleted > 0

    async def extend_ttl(
        self,
        workspace_id: str,
        session_id: str,
        ttl_seconds: int,
    ) -> bool:
        """Extend TTL for all keys in a session. Returns True if session existed."""
        ikey = _index_key(workspace_id, session_id)
        raw_index = await self._store.get(ikey)
        if raw_index is None:
            return False

        ids: list[str] = json.loads(raw_index)
        for record_id in ids:
            rkey = _record_key(workspace_id, session_id, record_id)
            await self._store.expire(rkey, ttl_seconds)
        await self._store.expire(ikey, ttl_seconds)
        return True
