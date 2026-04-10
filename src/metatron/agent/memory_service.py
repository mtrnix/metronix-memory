"""MemoryService — orchestrates agent memory across stores (WS1).

Sits at L4 (agent layer), composes L1 storage modules:
  - RedisSessionCache  (session memory — hot cache with TTL)
  - memory_graph.py    (Neo4j — relationships and graph queries)
  - TODO: PostgreSQL   (source of truth — Stage 3)
  - TODO: Qdrant       (embeddings + content — Qdrant stage)

Write-through pattern for session memory:
  cache_session() → Redis (primary) + Neo4j (best-effort)

Read pattern:
  get_session() → Redis first (fast path)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.storage.memory_graph import save_memory_to_graph

if TYPE_CHECKING:
    from metatron.storage.memory_redis import RedisSessionCache

logger = structlog.get_logger()


class MemoryService:
    """Orchestrates agent memory across Redis, Neo4j, (PG, Qdrant — TODO).

    Session memory: Redis is the primary store with auto-TTL.
    Neo4j receives a best-effort copy for graph traversal.
    PG and Qdrant integration is deferred to subsequent stages.
    """

    def __init__(self, redis_cache: RedisSessionCache) -> None:
        self._redis = redis_cache

    # ------------------------------------------------------------------
    # Session memory (Redis + Neo4j write-through)
    # ------------------------------------------------------------------

    async def cache_session(
        self,
        workspace_id: str,
        session_id: str,
        record: MemoryRecord,
        *,
        ttl_seconds: int | None = None,
    ) -> MemoryRecord:
        """Store a session memory record. Write-through: Redis + Neo4j.

        Redis is the primary store. Neo4j write is best-effort —
        a failure is logged but does not block the cache operation.
        """
        result = await self._redis.cache(
            workspace_id,
            session_id,
            record,
            ttl_seconds=ttl_seconds,
        )

        # Best-effort Neo4j write (sync, via thread pool)
        try:
            await asyncio.to_thread(save_memory_to_graph, record)
        except Exception:
            logger.warning(
                "memory_service.neo4j_write_failed",
                record_id=record.id,
                session_id=session_id,
                exc_info=True,
            )

        return result

    async def get_session(
        self,
        workspace_id: str,
        session_id: str,
        record_id: str,
    ) -> MemoryRecord | None:
        """Fetch a session record. Redis first.

        TODO: fallback to Neo4j/PG when Redis misses (Stage 3).
        """
        return await self._redis.get(workspace_id, session_id, record_id)

    async def list_session(
        self,
        workspace_id: str,
        session_id: str,
    ) -> list[MemoryRecord]:
        """List all records for a session."""
        return await self._redis.list(workspace_id, session_id)

    async def invalidate_session(
        self,
        workspace_id: str,
        session_id: str,
    ) -> int:
        """Drop all session records from cache."""
        return await self._redis.invalidate(workspace_id, session_id)

    async def extend_session_ttl(
        self,
        workspace_id: str,
        session_id: str,
        ttl_seconds: int,
    ) -> bool:
        """Extend TTL for a session."""
        return await self._redis.extend_ttl(workspace_id, session_id, ttl_seconds)

    # ------------------------------------------------------------------
    # Persistent memory (TODO — PG + Qdrant stages)
    # ------------------------------------------------------------------

    async def save(
        self,
        workspace_id: str,
        record: MemoryRecord,
    ) -> MemoryRecord:
        """Persist a memory record to all stores.

        TODO: PG (source of truth) + Qdrant (embeddings) + Neo4j (graph).
        """
        raise NotImplementedError("save requires PG + Qdrant (next stages)")

    async def promote(
        self,
        workspace_id: str,
        session_id: str,
        record_id: str,
        *,
        target_scope: MemoryScope = MemoryScope.PER_AGENT,
    ) -> MemoryRecord:
        """Promote a session record to persistent storage.

        TODO: read from Redis → write to PG + Qdrant + Neo4j → remove from Redis.
        """
        raise NotImplementedError("promote requires PG + Qdrant (next stages)")
