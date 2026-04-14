"""MemoryService — orchestrates agent memory across stores (WS1).

Sits at L4 (agent layer), composes L1 storage modules:
  - MemoryPostgresStore (source of truth — errors propagate)
  - MemoryQdrantStore   (content + embeddings — vector search)
  - RedisSessionCache   (session memory — hot cache with TTL)
  - memory_graph.py     (Neo4j — relationships and graph queries)

Write order for persistent memory:
  save() → dedup check (PG) → PG → Qdrant → Neo4j (best-effort)

Write-through for session memory:
  cache_session() → Redis (primary) + Neo4j (best-effort)
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

import structlog

from metatron.core.exceptions import MemoryNotFoundError
from metatron.core.models import MemoryRecord, MemoryScope, MemorySearchResult
from metatron.storage.memory_graph import (
    delete_memory_node,
    save_memory_to_graph,
)

if TYPE_CHECKING:
    from metatron.memory.search import MemorySearchService
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore
    from metatron.storage.memory_redis import RedisSessionCache

logger = structlog.get_logger()


class MemoryService:
    """Orchestrates agent memory across PG, Qdrant, Redis, Neo4j.

    PG is source of truth — failures propagate.
    Qdrant stores content + vectors — failures propagate.
    Neo4j stores graph edges — best-effort (failures logged, not raised).
    Redis caches session records with TTL.
    """

    def __init__(
        self,
        redis_cache: RedisSessionCache,
        qdrant_store: MemoryQdrantStore,
        pg_store: MemoryPostgresStore,
        *,
        workspace_id: str,
        search: MemorySearchService | None = None,
    ) -> None:
        self._redis = redis_cache
        self._qdrant = qdrant_store
        self._pg = pg_store
        self._workspace_id = workspace_id
        self._search = search

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_workspace(self, workspace_id: str) -> None:
        if workspace_id != self._workspace_id:
            msg = (
                f"workspace_id mismatch: service bound to {self._workspace_id!r}, "
                f"got {workspace_id!r}"
            )
            raise ValueError(msg)

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

    async def _delete_graph_best_effort(self, workspace_id: str, record_id: str) -> None:
        """Delete from Neo4j graph, swallowing errors."""
        try:
            await asyncio.to_thread(delete_memory_node, workspace_id, record_id)
        except Exception:
            logger.warning(
                "memory_service.neo4j_delete_failed",
                record_id=record_id,
                exc_info=True,
            )

    @staticmethod
    def _compute_content_hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

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
        self._check_workspace(workspace_id)
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
        """Fetch a session record. Redis first, PG fallback."""
        self._check_workspace(workspace_id)
        record = await self._redis.get(workspace_id, session_id, record_id)
        if record is not None:
            return record
        return await self._pg.get(workspace_id, record_id)

    async def list_session(
        self,
        workspace_id: str,
        session_id: str,
    ) -> list[MemoryRecord]:
        """List all records for a session."""
        self._check_workspace(workspace_id)
        return await self._redis.list(workspace_id, session_id)

    async def invalidate_session(
        self,
        workspace_id: str,
        session_id: str,
    ) -> int:
        """Drop all session records from cache."""
        self._check_workspace(workspace_id)
        return await self._redis.invalidate(workspace_id, session_id)

    async def extend_session_ttl(
        self,
        workspace_id: str,
        session_id: str,
        ttl_seconds: int,
    ) -> bool:
        """Extend TTL for a session."""
        self._check_workspace(workspace_id)
        return await self._redis.extend_ttl(workspace_id, session_id, ttl_seconds)

    # ------------------------------------------------------------------
    # Persistent memory (PG + Qdrant + Neo4j)
    # ------------------------------------------------------------------

    async def save(
        self,
        workspace_id: str,
        record: MemoryRecord,
    ) -> MemoryRecord:
        """Persist a memory record with content dedup.

        1. Compute content hash
        2. Check PG for existing record with same hash (dedup)
        3. If duplicate — return existing, skip writes
        4. PG write first (source of truth, errors propagate)
        5. Qdrant write (content + vectors, errors propagate)
        6. Neo4j write (graph edges, best-effort)

        Note: writes across PG, Qdrant and Neo4j are NOT atomic. A failure
        between steps (e.g. Qdrant down after PG commits) leaves the system
        in a transient inconsistent state — PG is the source of truth and
        derived stores are reconciled lazily (re-save / reset).

        Content hash is computed on the raw content string (exact-match
        semantics). Whitespace-only differences are distinct records.
        """
        self._check_workspace(workspace_id)
        record.content_hash = self._compute_content_hash(record.content)

        existing = await self._pg.get_by_hash(workspace_id, record.agent_id, record.content_hash)
        if existing is not None:
            logger.debug(
                "memory_service.dedup_hit",
                existing_id=existing.id,
                new_id=record.id,
            )
            return existing

        await self._pg.save(record)
        await self._qdrant.upsert(record)
        await self._write_graph_best_effort(record)
        return record

    async def get(
        self,
        workspace_id: str,
        record_id: str,
    ) -> MemoryRecord | None:
        """Fetch a persistent record from PG (source of truth)."""
        self._check_workspace(workspace_id)
        return await self._pg.get(workspace_id, record_id)

    async def delete(
        self,
        workspace_id: str,
        record_id: str,
    ) -> bool:
        """Delete a record from all stores. Returns True if PG had it."""
        self._check_workspace(workspace_id)
        deleted = await self._pg.delete(workspace_id, record_id)
        if not deleted:
            return False

        try:
            await self._qdrant.delete(record_id)
        except Exception:
            logger.warning(
                "memory_service.qdrant_delete_failed",
                record_id=record_id,
                exc_info=True,
            )

        await self._delete_graph_best_effort(workspace_id, record_id)
        return True

    async def list_records(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List records from PG with optional filters."""
        self._check_workspace(workspace_id)
        return await self._pg.list_records(
            workspace_id,
            agent_id=agent_id,
            scope=scope,
            limit=limit,
            offset=offset,
        )

    async def reset(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
    ) -> int:
        """Bulk-delete matching records from all stores.

        Uses DELETE ... RETURNING id in PG so the deleted-id set is
        authoritative (no race with concurrent inserts). Per-id deletes
        in Qdrant + Neo4j avoid the over-delete bug of `delete_by_agent`.
        """
        self._check_workspace(workspace_id)
        count, ids = await self._pg.reset(workspace_id, agent_id=agent_id, scope=scope)
        if not ids:
            return 0

        for record_id in ids:
            try:
                await self._qdrant.delete(record_id)
            except Exception:
                logger.warning(
                    "memory_service.qdrant_reset_failed",
                    record_id=record_id,
                    exc_info=True,
                )
            await self._delete_graph_best_effort(workspace_id, record_id)

        return count

    async def promote(
        self,
        workspace_id: str,
        session_id: str,
        record_id: str,
        *,
        target_scope: MemoryScope = MemoryScope.PER_AGENT,
    ) -> MemoryRecord:
        """Promote a session record to persistent storage.

        Reads from Redis (fallback PG) -> changes scope -> saves to
        PG + Qdrant + Neo4j -> deletes record from Redis.

        Dedup edge case: if another record with identical content already
        exists for this agent, its scope is upgraded to target_scope (in PG
        + Qdrant) so the promotion intent is honoured even on a dedup hit.
        """
        self._check_workspace(workspace_id)
        record = await self._redis.get(workspace_id, session_id, record_id)
        if record is None:
            record = await self._pg.get(workspace_id, record_id)
        if record is None:
            msg = f"Record {record_id} not found in session {session_id}"
            raise MemoryNotFoundError(msg)

        record.scope = target_scope
        record.content_hash = self._compute_content_hash(record.content)

        existing = await self._pg.get_by_hash(workspace_id, record.agent_id, record.content_hash)
        if existing is not None:
            if existing.scope != target_scope:
                existing.scope = target_scope
                await self._pg.save(existing)
                await self._qdrant.upsert(existing)
                await self._write_graph_best_effort(existing)
            result = existing
        else:
            await self._pg.save(record)
            await self._qdrant.upsert(record)
            await self._write_graph_best_effort(record)
            result = record

        try:
            await self._redis.delete_record(workspace_id, session_id, record_id)
        except Exception:
            logger.warning(
                "memory_service.redis_cleanup_failed",
                record_id=record_id,
                session_id=session_id,
                exc_info=True,
            )
        return result

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
        self._check_workspace(workspace_id)
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
