"""MemoryService — orchestrates agent memory across stores (WS1).

Sits at L4 (agent layer), composes L1 storage modules:
  - RedisSessionCache   (session memory — hot cache with TTL)
  - MemoryQdrantStore   (content + embeddings — vector search)
  - memory_graph.py     (Neo4j — relationships and graph queries)
  - TODO: PostgreSQL    (source of truth — next stage)

Write-through pattern for session memory:
  cache_session() → Redis (primary) + Neo4j (best-effort)

Persistent memory:
  save() → Qdrant (content + vectors) + Neo4j (graph, best-effort)

Read pattern:
  get_session() → Redis first (fast path)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from metatron.core.exceptions import MemoryNotFoundError
from metatron.core.models import MemoryRecord, MemoryScope, MemorySearchResult
from metatron.storage.memory_graph import save_memory_to_graph

if TYPE_CHECKING:
    from metatron.memory.search import MemorySearchService
    from metatron.storage.memory_qdrant import MemoryQdrantStore
    from metatron.storage.memory_redis import RedisSessionCache

logger = structlog.get_logger()


class MemoryService:
    """Orchestrates agent memory across Redis, Qdrant, Neo4j (PG — TODO).

    Session memory: Redis is the primary store with auto-TTL.
    Persistent memory: Qdrant stores content + vectors, Neo4j stores graph.
    Neo4j writes are best-effort — failures are logged, not raised.
    PG (source of truth) integration is deferred to next stage.
    """

    def __init__(
        self,
        redis_cache: RedisSessionCache,
        qdrant_store: MemoryQdrantStore,
        *,
        search: MemorySearchService | None = None,
    ) -> None:
        self._redis = redis_cache
        self._qdrant = qdrant_store
        self._search = search

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _write_graph_best_effort(self, record: MemoryRecord) -> None:
        """Write to Neo4j graph, swallowing errors (best-effort)."""
        try:
            await asyncio.to_thread(save_memory_to_graph, record)
        except Exception:
            logger.warning(
                "memory_service.neo4j_write_failed",
                record_id=record.id,
                exc_info=True,
            )

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

        await self._write_graph_best_effort(record)
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
    # Persistent memory (Qdrant + Neo4j; PG — TODO next stage)
    # ------------------------------------------------------------------

    async def save(
        self,
        workspace_id: str,
        record: MemoryRecord,
    ) -> MemoryRecord:
        """Persist a memory record: Qdrant (content + vectors) + Neo4j (graph).

        Qdrant failure propagates (primary store). Neo4j is best-effort.
        TODO: add PG as source of truth in next stage.
        """
        await self._qdrant.upsert(record)
        await self._write_graph_best_effort(record)
        return record

    async def promote(
        self,
        workspace_id: str,
        session_id: str,
        record_id: str,
        *,
        target_scope: MemoryScope = MemoryScope.PER_AGENT,
    ) -> MemoryRecord:
        """Promote a session record to persistent storage.

        Reads from Redis → changes scope → writes to Qdrant + Neo4j →
        deletes record from Redis (key + index).
        TODO: add PG write in next stage.
        """
        record = await self._redis.get(workspace_id, session_id, record_id)
        if record is None:
            msg = f"Record {record_id} not found in session {session_id}"
            raise MemoryNotFoundError(msg)

        record.scope = target_scope
        await self.save(workspace_id, record)
        await self._redis.delete_record(workspace_id, session_id, record_id)

        return record

    # ------------------------------------------------------------------
    # Hybrid search (delegates to MemorySearchService)
    # ------------------------------------------------------------------

    async def search(
        self,
        workspace_id: str,
        query: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        tags: list[str] | None = None,
        session_id: str | None = None,
        top_k: int = 5,
    ) -> list[MemorySearchResult]:
        if self._search is None:
            raise RuntimeError("search not configured")
        return await self._search.hybrid_search(
            workspace_id,
            query,
            agent_id=agent_id,
            scope=scope,
            tags=tags,
            session_id=session_id,
            top_k=top_k,
        )
