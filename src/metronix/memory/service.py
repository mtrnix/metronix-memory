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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from metronix.core.config import get_settings
from metronix.core.events import (
    FRESHNESS_REVIEW_RESOLVED,
    MEMORY_DELETED,
    MEMORY_PROMOTED,
    MEMORY_RESET,
    MEMORY_STORED,
)
from metronix.core.exceptions import MemoryNotFoundError
from metronix.core.models import (
    LifecycleStatus,
    MachineEvent,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    ReviewEntry,
)
from metronix.ingestion.dedup import simhash as _simhash
from metronix.memory.freshness.producer import enqueue_if_enabled
from metronix.memory.resolution import ReviewResolution, parse_action
from metronix.storage.memory_graph import (
    delete_memory_node,
    get_memory_neighborhood,
    save_memory_to_graph,
)

if TYPE_CHECKING:
    from metronix.core.events import EventBus
    from metronix.memory.search import MemorySearchService
    from metronix.storage.freshness_pg import FreshnessStore
    from metronix.storage.memory_postgres import MemoryPostgresStore
    from metronix.storage.memory_qdrant import MemoryQdrantStore
    from metronix.storage.memory_redis import RedisSessionCache

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
        # Set on first skipped emission so the "bus not wired" warning fires
        # exactly once per service instance (see ``_emit_bus``).
        self._warned_no_bus = False

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

    async def _emit_bus(self, name: str, payload: dict[str, object]) -> None:
        """Emit an event on the EventBus; no-op when bus is not wired."""
        if self._event_bus is None:
            if not self._warned_no_bus:
                logger.warning(
                    "event_bus_not_wired",
                    service="MemoryService",
                    workspace_id=self._workspace_id,
                )
                self._warned_no_bus = True
            return
        await self._event_bus.emit(name, payload)

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
        """Store a session memory record.

        Write-through: Redis (primary) + PG (best-effort) + Neo4j.

        Redis is the primary store — its failure propagates.  PG is a best-effort
        dual-write so session rows appear in ``GET /knowledge/records?lifetime=session``;
        a PG failure is logged at WARNING and never blocks the Redis path (D-P2-03).
        Neo4j write is also best-effort.

        NOTE: this method may mutate the input ``record`` in-place to fill
        ``session_id`` and ``ttl_expires_at`` when not already set.  Callers
        must not rely on the input record being unchanged after this call.
        """
        self._check_workspace(workspace_id)

        # Resolve TTL once so both Redis and PG share the same expiry value.
        resolved_ttl = (
            ttl_seconds if ttl_seconds is not None else get_settings().memory_session_ttl
        )

        # Populate session_id and ttl_expires_at on the record *before* the
        # Redis write so the stored object is complete.  Only set when not
        # already populated by the caller (idempotent / test-friendly).
        if record.session_id is None:
            record.session_id = session_id
        if record.ttl_expires_at is None:
            record.ttl_expires_at = datetime.now(UTC) + timedelta(seconds=resolved_ttl)

        result = await self._redis.cache(
            workspace_id,
            session_id,
            record,
            ttl_seconds=resolved_ttl,
        )

        await self._write_graph_best_effort(record)
        await self._dual_write_session_to_pg_best_effort(record)
        await enqueue_if_enabled(workspace_id, result.id, "knowledge_changed")
        await self._emit_bus(
            MEMORY_STORED,
            {
                "workspace_id": self._workspace_id,
                "agent_id": record.agent_id,
                "record_id": result.id,
                "scope": "session",
                "source_type": record.source_type,
                "session_id": session_id,
            },
        )
        return result

    async def _dual_write_session_to_pg_best_effort(self, record: MemoryRecord) -> None:
        """Best-effort PG write for session records.

        Swallows any exception — PG failure must not block the Redis path.
        Logs ``memory.session.pg_write_failed`` so operators can grep.
        """
        try:
            await self._pg.save(record)
        except Exception:
            logger.warning(
                "memory.session.pg_write_failed",
                record_id=record.id,
                workspace_id=record.workspace_id,
                agent_id=record.agent_id,
                session_id=record.session_id,
                exc_info=True,
            )

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

        # Compute SimHash for near-duplicate health tracking (MTRNIX-277).
        # Done after the dedup-hit check so rejected duplicates do not waste time.
        record.content_simhash = _simhash(record.content)

        await self._pg.save(record)
        await self._qdrant.upsert(record)
        await self._write_graph_best_effort(record)
        await enqueue_if_enabled(workspace_id, record.id, "knowledge_changed")
        await self._emit_bus(
            MEMORY_STORED,
            {
                "workspace_id": self._workspace_id,
                "agent_id": record.agent_id,
                "record_id": record.id,
                "scope": record.scope.value if record.scope else None,
                "source_type": record.source_type,
                "content_hash": record.content_hash,
                "session_id": record.session_id,
                "kind": record.kind.value,
            },
        )
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
        # Pre-fetch to learn agent_id / session_id for the event payload
        # before the record is removed.
        existing = await self._pg.get(workspace_id, record_id)
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
        if existing is not None:
            await self._emit_bus(
                MEMORY_DELETED,
                {
                    "workspace_id": self._workspace_id,
                    "agent_id": existing.agent_id,
                    "record_id": record_id,
                    "session_id": existing.session_id,
                    "kind": existing.kind.value,
                },
            )
        return True

    async def delete_many(
        self,
        workspace_id: str,
        record_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """Delete multiple records from all stores.

        Delegates to :meth:`delete` per id so each record gets the same
        best-effort Qdrant/Neo4j cleanup and event emission as a single
        delete. Returns ``(deleted_ids, not_found_ids)``.
        """
        self._check_workspace(workspace_id)
        deleted: list[str] = []
        not_found: list[str] = []
        for record_id in record_ids:
            if await self.delete(workspace_id, record_id):
                deleted.append(record_id)
            else:
                not_found.append(record_id)
        return deleted, not_found

    async def list_records(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        kind_filter: list[MemoryKind] | None = None,
        source_type_filter: list[str] | None = None,
        status: list[LifecycleStatus] | None = None,
        lifetime: str = "all",
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List records from PG with optional filters.

        ``status`` is forwarded to the PG store which applies a ``status =
        ANY(:status_list)`` WHERE clause when provided (MTRNIX-324).
        ``kind_filter`` is forwarded for kind-based filtering (MTRNIX-275).
        ``source_type_filter`` is forwarded for source-type filtering (MTRNIX-274).
        ``lifetime`` forwards to the PG store for session/persistent filtering
        (phase-2 memory-scopes). Default ``"all"`` keeps all existing callers
        unaffected; the route layer enforces ``"persistent"`` as the user-facing
        default (D-P2-08).
        ``None`` means no filter — all values are returned.
        """
        self._check_workspace(workspace_id)
        return await self._pg.list_records(
            workspace_id,
            agent_id=agent_id,
            scope=scope,
            kind_filter=kind_filter,
            source_type_filter=source_type_filter,
            status=status,
            lifetime=lifetime,
            limit=limit,
            offset=offset,
        )

    async def count_records(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        kind_filter: list[MemoryKind] | None = None,
        source_type_filter: list[str] | None = None,
        status: list[LifecycleStatus] | None = None,
        lifetime: str = "all",
    ) -> int:
        """Count records matching the same filter surface as :meth:`list_records`.

        Pagination companion: routes pair this with ``list_records`` (same
        filters, no limit/offset) to expose an exact ``total``. Goes through
        the service (not ``pg_store`` directly) so ``_check_workspace`` gates
        the call like every other public method.
        """
        self._check_workspace(workspace_id)
        return await self._pg.count_records(
            workspace_id,
            agent_id=agent_id,
            scope=scope,
            kind_filter=kind_filter,
            source_type_filter=source_type_filter,
            status=status,
            lifetime=lifetime,
        )

    async def list_preferences(
        self,
        workspace_id: str,
        agent_id: str,
    ) -> list[MemoryRecord]:
        """Return all active preference+pinned records for an agent.

        Always-on context for the assembler: these records are injected
        into the agent prompt without retrieval. Excludes ARCHIVED and
        SUPERSEDED records — stale preferences must not appear in the
        assembled prompt (MTRNIX-275).
        """
        self._check_workspace(workspace_id)
        return await self._pg.list_records(
            workspace_id,
            agent_id=agent_id,
            kind_filter=[MemoryKind.PREFERENCE, MemoryKind.PINNED],
            status=[LifecycleStatus.ACTIVE, LifecycleStatus.CANDIDATE],
            limit=1000,
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
            await self._emit_bus(
                MEMORY_DELETED,
                {
                    "workspace_id": self._workspace_id,
                    "agent_id": agent_id,
                    "record_id": record_id,
                },
            )

        await self._emit_bus(
            MEMORY_RESET,
            {
                "workspace_id": self._workspace_id,
                "agent_id": agent_id,
                "scope": scope.value if scope else None,
                "count": count,
            },
        )
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
        await self._emit_bus(
            MEMORY_PROMOTED,
            {
                "workspace_id": self._workspace_id,
                "agent_id": result.agent_id,
                "record_id": result.id,
                "from_scope": "session",
                "to_scope": target_scope.value,
                "session_id": session_id,
            },
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
        status_filter: list[LifecycleStatus] | None = None,
        kind_filter: list[MemoryKind] | None = None,
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
            kind_filter=kind_filter,
        )

    # ------------------------------------------------------------------
    # Memory graph neighbourhood (MTRNIX-324)
    # ------------------------------------------------------------------

    async def get_graph_neighborhood(
        self,
        workspace_id: str,
        seed_record_id: str,
        *,
        depth: int = 1,
    ) -> tuple[list[MemoryRecord], list[dict[str, Any]]]:
        """Return the (depth)-hop neighbourhood around a memory record.

        Delegates to the Neo4j ``get_memory_neighborhood`` helper (via
        ``asyncio.to_thread``). Falls back gracefully when Neo4j is down:
        returns the seed record from PG (when it exists) and an empty edge
        list.

        Always validates:
          * ``workspace_id`` matches the service's bound workspace.
          * ``0 < depth <= 3`` (prevents fan-out explosions in large graphs).

        Returns a ``(records, edges)`` tuple where:
          * ``records`` — :class:`MemoryRecord` instances hydrated from PG.
            Records returned by Neo4j but absent in PG are dropped (cross-
            workspace defence-in-depth; PG is the source of truth).
          * ``edges`` — raw edge dicts from the storage helper
            (``{source, target, type, metadata?}``).

        ``depth`` controls direct memory-to-memory traversal (``LINKED_TO``
        chains). Bridge edges via Agent / Entity / Session / Document are
        always returned at exactly 2 hops from the seed regardless of
        ``depth`` — Phase 1 semantics; deeper bridge expansion is a follow-up.

        Raises:
          ``ValueError`` — workspace mismatch or invalid depth.
        """
        self._check_workspace(workspace_id)
        if not (0 < depth <= 3):
            msg = f"depth must be between 1 and 3 inclusive, got {depth}"
            raise ValueError(msg)

        record_ids: list[str] = [seed_record_id]
        edges: list[dict[str, Any]] = []

        try:
            result = await asyncio.to_thread(
                get_memory_neighborhood,
                workspace_id,
                seed_record_id,
                depth,
            )
            record_ids = result["record_ids"]
            edges = result["edges"]
        except (ServiceUnavailable, SessionExpired, ConnectionError, OSError):
            logger.warning(
                "memory_service.neighborhood.neo4j_unavailable",
                workspace_id=workspace_id,
                seed_record_id=seed_record_id,
                depth=depth,
                exc_info=True,
            )
            # Fall back: only the seed, no edges

        # De-dup while preserving seed priority (seed first).
        seen: set[str] = set()
        unique_ids: list[str] = []
        for rid in [seed_record_id, *record_ids]:
            if rid not in seen:
                seen.add(rid)
                unique_ids.append(rid)

        # Hydrate from PG — drops ids not in this workspace (cross-ws defence).
        records: list[MemoryRecord] = []
        for rid in unique_ids:
            rec = await self._pg.get(workspace_id, rid)
            if rec is not None:
                records.append(rec)

        return records, edges

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

        # 2b. MTRNIX-395: a duplicate pair may have a mirror review entry
        # (target=related, related=target) created when the partner record
        # was processed in the opposite direction. Resolving this entry
        # settles the pair, so the mirror is moot — cascade-delete it in the
        # same transaction. Only meaningful for paired reasons (those carry a
        # ``related_record_id``); low-confidence entries have none.
        mirror_id: str | None = None
        mirror_target_id: str = ""  # partner record (B) — set iff mirror found
        if entry.related_record_id:
            mirror = await self._freshness_store.find_review_entry(
                workspace_id,
                target_id=entry.related_record_id,
                target_kind="memory_record",
                reason=entry.reason,
                related_record_id=entry.target_id,
            )
            if mirror is not None and mirror.id != review_id:
                mirror_id = mirror.id
                mirror_target_id = mirror.target_id

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

        # 4-6. Transition + delete review + audit event — atomic in a single
        # transaction (MTRNIX-319 fix). Previously these ran as three
        # separate ``engine.begin()`` blocks; a failure on the third could
        # leave partially-committed state (lifecycle changed, review deleted,
        # but no audit row), and the caller received a misleading error
        # while the DB had already moved on. All three stores share the
        # same AsyncEngine (wired in ``_memory_deps.py``), so a single
        # transaction can span all of them.
        truncated_notes = (notes or "")[:1024]
        evt = MachineEvent(
            workspace_id=workspace_id,
            event_type="freshness_review_resolved",
            actor=actor,
            target_kind="memory_record",
            target_id=entry.target_id,
            payload={
                "review_entry_id": review_id,
                "mirror_review_entry_id": mirror_id,
                "action": action_kind,
                "merge_into_target_id": merge_target,
                "old_status": old_status,
                "new_status": new_status.value,
                "superseded_by": superseded_by,
                "notes": truncated_notes,
            },
        )
        async with self._pg.begin() as conn:
            # ``superseded_by=None`` means "leave unchanged" per
            # ``update_lifecycle`` semantics; we only pass it for merge_into.
            # ``bump_updated_at=True`` (MTRNIX-395): a human resolution is a
            # freshness signal — refresh the clock so a kept record does not
            # immediately re-STALE on the next scheduled scan.
            await self._pg.update_lifecycle(
                workspace_id,
                entry.target_id,
                status=new_status,
                verification_state=verification_state,
                superseded_by=superseded_by,
                bump_updated_at=True,
                conn=conn,
            )
            await self._freshness_store.delete_review_entry(workspace_id, review_id, conn=conn)
            if mirror_id is not None:
                # Cascade-delete the mirror entry (MTRNIX-395) so the pair
                # leaves the queue as a unit. This is intentional for ALL
                # actions, including ``merge_into`` a third record: the pair
                # A<->B is considered settled once either side is resolved, so
                # the B->A mirror is moot even when A merges into some C. If B
                # is genuinely similar to the survivor, the Reconciler re-flags
                # it on B's next pipeline pass.
                await self._freshness_store.delete_review_entry(workspace_id, mirror_id, conn=conn)
                # Give the partner record (B) its own audit row so a per-record
                # review-history view explains why its queue entry vanished —
                # otherwise the only trace is the ``mirror_review_entry_id`` on
                # this (A) event. Same event_type so it surfaces in the shared
                # audit stream; ``action="cascade_mirror"`` distinguishes it.
                mirror_evt = MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_review_resolved",
                    actor=actor,
                    target_kind="memory_record",
                    target_id=mirror_target_id,
                    payload={
                        "review_entry_id": mirror_id,
                        "action": "cascade_mirror",
                        "resolved_via_review_entry_id": review_id,
                        "resolved_via_target_id": entry.target_id,
                        "reason": entry.reason,
                    },
                )
                await self._freshness_store.save_machine_event(mirror_evt, conn=conn)
            saved_evt = await self._freshness_store.save_machine_event(evt, conn=conn)

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
