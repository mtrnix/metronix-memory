"""MemoryService — orchestrates agent memory across stores (WS1).

L3 orchestration service composing L1 storage modules:
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

from metatron.core.events import FRESHNESS_REVIEW_RESOLVED
from metatron.core.exceptions import MemoryNotFoundError
from metatron.core.models import (
    LifecycleStatus,
    MachineEvent,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    ReviewEntry,
)
from metatron.memory.freshness.producer import enqueue_if_enabled
from metatron.memory.resolution import ReviewResolution, parse_action
from metatron.storage.memory_graph import (
    delete_memory_node,
    save_memory_to_graph,
)

if TYPE_CHECKING:
    from metatron.core.events import EventBus
    from metatron.memory.search import MemorySearchService
    from metatron.storage.freshness_pg import FreshnessStore
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
        freshness_store: FreshnessStore | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._redis = redis_cache
        self._qdrant = qdrant_store
        self._pg = pg_store
        self._workspace_id = workspace_id
        self._search = search
        # MTRNIX-314: optional freshness store dep for the review-queue
        # methods (``list_review_entries`` / ``resolve_review``). Legacy
        # construction paths leave it None; the methods raise RuntimeError
        # when called without wiring.
        self._freshness_store = freshness_store
        self._event_bus = event_bus

    @property
    def pg_store(self) -> MemoryPostgresStore:
        """Public access to PG store for list/update tools."""
        return self._pg

    @property
    def qdrant_store(self) -> MemoryQdrantStore:
        """Public access to Qdrant store for update tool."""
        return self._qdrant

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
        await enqueue_if_enabled(workspace_id, result.id, "knowledge_changed")
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
        await enqueue_if_enabled(workspace_id, record.id, "knowledge_changed")
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
        await enqueue_if_enabled(workspace_id, record_id, "knowledge_deleted")
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
        await enqueue_if_enabled(workspace_id, result.id, "scope_changed")
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
        status_filter: list[LifecycleStatus] | None = None,
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
            status_filter=status_filter,
        )

    # ------------------------------------------------------------------
    # Freshness review queue (MTRNIX-314)
    # ------------------------------------------------------------------

    async def list_review_entries(
        self,
        workspace_id: str,
        *,
        record_id: str | None = None,
        reason: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ReviewEntry], int]:
        """List pending review entries for ``target_kind=memory_record``.

        Returns a ``(page, total)`` tuple for UI pagination.

        Raises ``RuntimeError`` if the service was constructed without a
        ``FreshnessStore`` dependency (legacy paths).
        """
        self._check_workspace(workspace_id)
        if self._freshness_store is None:
            raise RuntimeError("freshness_store not configured")
        entries = await self._freshness_store.list_review_entries(
            workspace_id,
            target_kind="memory_record",
            record_id=record_id,
            reason=reason,
            limit=limit,
            offset=offset,
        )
        total = await self._freshness_store.count_review_entries(
            workspace_id,
            target_kind="memory_record",
            record_id=record_id,
            reason=reason,
        )
        return entries, total

    async def resolve_review(
        self,
        workspace_id: str,
        *,
        review_id: str,
        action: str,
        notes: str | None = None,
        actor: str = "mcp_caller",
    ) -> ReviewResolution:
        """Apply a resolution (``keep``/``archive``/``merge_into:<id>``/``discard``).

        Orchestrates:
          1. Parse action and load review entry.
          2. Load target memory record (must exist).
          3. For ``merge_into``: validate the target id exists in the workspace.
          4. Update memory record lifecycle (soft transitions).
          5. Delete the review entry.
          6. Append a ``freshness_review_resolved`` MachineEvent.
          7. Best-effort Qdrant payload sync for the new status.
          8. Best-effort ``FRESHNESS_REVIEW_RESOLVED`` EventBus emit.

        Returns a ``ReviewResolution`` shaped like the MCP response.

        Raises:
          * ``MemoryNotFoundError`` — review entry or target record missing.
          * ``ValueError`` — malformed action or missing merge target.
          * ``RuntimeError`` — freshness_store not wired.
        """
        self._check_workspace(workspace_id)
        if self._freshness_store is None:
            raise RuntimeError("freshness_store not configured")

        action_kind, merge_target = parse_action(action)

        # 1. Load the review entry (search by target_kind, then filter by id).
        # ``find_review_entry`` doesn't support lookup-by-id, so we paginate
        # with a reasonable cap. Review tables are expected to be small.
        entries = await self._freshness_store.list_review_entries(
            workspace_id, target_kind="memory_record", limit=1000
        )
        entry = next((e for e in entries if e.id == review_id), None)
        if entry is None:
            msg = f"Review entry {review_id} not found or already resolved"
            raise MemoryNotFoundError(msg)

        # 2. Load the target record.
        record = await self._pg.get(workspace_id, entry.target_id)
        if record is None:
            msg = f"Record {entry.target_id} not found"
            raise MemoryNotFoundError(msg)
        old_status = record.status.value

        # 3. Resolve the new status / verification_state / superseded_by.
        new_status: LifecycleStatus
        if action_kind == "merge_into":
            assert merge_target is not None  # parse_action guarantees
            target_rec = await self._pg.get(workspace_id, merge_target)
            if target_rec is None:
                msg = f"merge_into target {merge_target} not found"
                raise ValueError(msg)
            new_status = LifecycleStatus.SUPERSEDED
            verification_state = "merged_via_review"
            superseded_by: str | None = merge_target
        elif action_kind == "keep":
            new_status = LifecycleStatus.ACTIVE
            verification_state = "keep_resolved"
            superseded_by = None
        elif action_kind == "archive":
            new_status = LifecycleStatus.ARCHIVED
            verification_state = "archived_via_review"
            superseded_by = None
        elif action_kind == "discard":
            new_status = LifecycleStatus.ARCHIVED
            verification_state = "discarded_via_review"
            superseded_by = None
        else:
            msg = f"Unknown action: {action}"
            raise ValueError(msg)

        # 4. Transition. ``superseded_by=None`` means "leave unchanged" per
        # ``update_lifecycle`` semantics; we only pass it for merge_into.
        await self._pg.update_lifecycle(
            workspace_id,
            entry.target_id,
            status=new_status,
            verification_state=verification_state,
            superseded_by=superseded_by,
        )

        # 5. Delete the review entry.
        await self._freshness_store.delete_review_entry(workspace_id, review_id)

        # 6. MachineEvent audit row.
        truncated_notes = (notes or "")[:1024]
        evt = MachineEvent(
            workspace_id=workspace_id,
            event_type="freshness_review_resolved",
            actor=actor,
            target_kind="memory_record",
            target_id=entry.target_id,
            payload={
                "review_entry_id": review_id,
                "action": action_kind,
                "merge_into_target_id": merge_target,
                "old_status": old_status,
                "new_status": new_status.value,
                "superseded_by": superseded_by,
                "notes": truncated_notes,
            },
        )
        saved_evt = await self._freshness_store.save_machine_event(evt)

        # 7. Best-effort Qdrant payload sync.
        try:
            await self._qdrant.update_payload(entry.target_id, {"status": new_status.value})
        except Exception:
            logger.warning(
                "memory_service.review_resolve.qdrant_sync_failed",
                record_id=entry.target_id,
                exc_info=True,
            )

        # 8. Best-effort EventBus emit.
        if self._event_bus is not None:
            try:
                await self._event_bus.emit(
                    FRESHNESS_REVIEW_RESOLVED,
                    {
                        "workspace_id": workspace_id,
                        "target_kind": "memory_record",
                        "target_id": entry.target_id,
                        "review_entry_id": review_id,
                        "action": action_kind,
                        "old_status": old_status,
                        "new_status": new_status.value,
                    },
                )
            except Exception:
                logger.warning(
                    "memory_service.review_resolve.bus_emit_failed",
                    exc_info=True,
                )

        return ReviewResolution(
            review_id=review_id,
            target_id=entry.target_id,
            action=action_kind,
            old_status=old_status,
            new_status=new_status.value,
            superseded_by=superseded_by,
            machine_event_id=saved_evt.id,
        )
