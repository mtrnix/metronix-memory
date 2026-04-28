"""PostgreSQL store for Agent Memory (WS1).

Source of truth for memory records and snapshots. Stores all fields
including content (unlike Neo4j which is metadata-only).

Uses raw SQL via SQLAlchemy async engine — same pattern as postgres.py.
This is an L1 storage module — no business logic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

from metatron.core.models import (
    LifecycleStatus,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySnapshot,
    MemoryStatus,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = structlog.get_logger()

# ------------------------------------------------------------------
# Row → dataclass helpers
# ------------------------------------------------------------------

_RECORD_COLUMNS = (
    "id, workspace_id, agent_id, scope, kind, source_type, content, "
    "tags, importance_score, ttl_expires_at, content_hash, "
    "session_id, metadata, created_at, updated_at, "
    "status, freshness_score, superseded_by, valid_from, valid_until, "
    "evidence_count, verification_state"
)

# Columns that the standard save() path writes explicitly. New lifecycle
# columns (status, freshness_score, ...) rely on PG server defaults
# (ACTIVE / 0.5 / NULL / 0 / NULL) so pre-MTRNIX-304 callers stay unchanged.
# The freshness pipeline updates lifecycle fields via update_lifecycle().
_RECORD_INSERT_COLUMNS = (
    "id, workspace_id, agent_id, scope, kind, source_type, content, "
    "tags, importance_score, ttl_expires_at, content_hash, "
    "session_id, metadata, created_at, updated_at"
)

_SNAPSHOT_COLUMNS = (
    "id, workspace_id, agent_id, label, trigger, record_count, "
    "content_hash, size_bytes, storage_path, created_at"
)


def _as_aware(value: Any) -> datetime | None:
    """Return a tz-aware UTC datetime or None. Handles naive legacy rows."""
    if value is None:
        return None
    dt: datetime = value
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _row_to_record(m: Any) -> MemoryRecord:
    """Convert a DB row mapping to MemoryRecord.

    New freshness columns are read via ``mapping.get(...)`` so mocks that only
    set legacy keys (pre-MTRNIX-304 fixtures) keep working with safe defaults.
    """
    ttl = _as_aware(m["ttl_expires_at"])
    created = _as_aware(m["created_at"])

    def _opt(key: str, default: Any = None) -> Any:
        try:
            return m[key] if m[key] is not None else default
        except (KeyError, LookupError):
            getter = getattr(m, "get", None)
            if callable(getter):
                val = getter(key, default)
                return val if val is not None else default
            return default

    status_raw = _opt("status", MemoryStatus.ACTIVE.value)
    try:
        status = MemoryStatus(status_raw)
    except ValueError:
        status = MemoryStatus.ACTIVE

    # kind (MTRNIX-275): read via _opt for pre-migration rows
    kind_raw = _opt("kind", MemoryKind.FACT.value)
    try:
        kind = MemoryKind(kind_raw)
    except ValueError:
        kind = MemoryKind.FACT

    return MemoryRecord(
        id=m["id"],
        workspace_id=m["workspace_id"],
        agent_id=m["agent_id"],
        scope=MemoryScope(m["scope"]),
        kind=kind,
        source_type=m["source_type"],
        content=m["content"],
        tags=m["tags"] if isinstance(m["tags"], list) else json.loads(m["tags"]),
        importance_score=m["importance_score"],
        ttl_expires_at=ttl,
        content_hash=m["content_hash"],
        session_id=m["session_id"],
        metadata=(m["metadata"] if isinstance(m["metadata"], dict) else json.loads(m["metadata"])),
        created_at=created or datetime.now(UTC),
        status=status,
        freshness_score=float(_opt("freshness_score", 0.5)),
        superseded_by=_opt("superseded_by"),
        valid_from=_as_aware(_opt("valid_from")),
        valid_until=_as_aware(_opt("valid_until")),
        evidence_count=int(_opt("evidence_count", 0)),
        verification_state=_opt("verification_state"),
        updated_at=_as_aware(_opt("updated_at")),
    )


def _row_to_snapshot(m: Any) -> MemorySnapshot:
    """Convert a DB row mapping to MemorySnapshot."""
    created = m["created_at"]
    if created and not getattr(created, "tzinfo", None):
        created = created.replace(tzinfo=UTC)
    return MemorySnapshot(
        id=m["id"],
        workspace_id=m["workspace_id"],
        agent_id=m["agent_id"],
        label=m["label"],
        trigger=m["trigger"],
        record_count=m["record_count"],
        content_hash=m["content_hash"],
        size_bytes=m["size_bytes"],
        storage_path=m["storage_path"],
        created_at=created or datetime.now(UTC),
    )


class MemoryPostgresStore:
    """Async PostgreSQL store for agent memory records and snapshots.

    Source of truth — all other stores (Qdrant, Neo4j, Redis) are derived.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def begin(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Open a transactional connection on the underlying engine.

        Thin public wrapper around ``AsyncEngine.begin()``. Lets callers
        coordinate writes across multiple store methods in a single
        transaction by passing the yielded connection via the optional
        ``conn`` kwarg on each method (``update_lifecycle``, etc). Used by
        ``MemoryService.resolve_review`` to make the update + delete +
        machine-event-insert triple atomic (MTRNIX-319).
        """
        return self._engine.begin()

    # ------------------------------------------------------------------
    # Records — CRUD
    # ------------------------------------------------------------------

    async def save(self, record: MemoryRecord) -> MemoryRecord:
        """Insert or update a memory record (upsert by id).

        Sets updated_at to current time on every call.
        """
        now = datetime.now(UTC)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(f"""
                    INSERT INTO memory_records ({_RECORD_INSERT_COLUMNS})
                    VALUES (:id, :workspace_id, :agent_id, :scope, :kind,
                            :source_type,
                            :content, CAST(:tags AS jsonb), :importance_score, :ttl_expires_at,
                            :content_hash, :session_id, CAST(:metadata AS jsonb),
                            :created_at, :updated_at)
                    ON CONFLICT (id) DO UPDATE SET
                        scope = EXCLUDED.scope,
                        kind = EXCLUDED.kind,
                        source_type = EXCLUDED.source_type,
                        content = EXCLUDED.content,
                        tags = EXCLUDED.tags,
                        importance_score = EXCLUDED.importance_score,
                        ttl_expires_at = EXCLUDED.ttl_expires_at,
                        content_hash = EXCLUDED.content_hash,
                        session_id = EXCLUDED.session_id,
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "id": record.id,
                    "workspace_id": record.workspace_id,
                    "agent_id": record.agent_id,
                    "scope": record.scope.value,
                    "kind": record.kind.value,
                    "source_type": record.source_type,
                    "content": record.content,
                    "tags": json.dumps(record.tags),
                    "importance_score": record.importance_score,
                    "ttl_expires_at": record.ttl_expires_at,
                    "content_hash": record.content_hash,
                    "session_id": record.session_id,
                    "metadata": json.dumps(record.metadata),
                    "created_at": record.created_at,
                    "updated_at": now,
                },
            )
        logger.debug("memory_pg.saved", record_id=record.id)
        return record

    async def get(self, workspace_id: str, record_id: str) -> MemoryRecord | None:
        """Fetch a single record by id within the workspace."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_RECORD_COLUMNS}
                    FROM memory_records
                    WHERE id = :id AND workspace_id = :ws
                """),
                {"id": record_id, "ws": workspace_id},
            )
            row = result.first()
        if row is None:
            return None
        return _row_to_record(row._mapping)

    async def delete(self, workspace_id: str, record_id: str) -> bool:
        """Delete a record. Returns True if it existed."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM memory_records WHERE id = :id AND workspace_id = :ws"),
                {"id": record_id, "ws": workspace_id},
            )
            deleted = result.rowcount > 0
        if deleted:
            logger.debug("memory_pg.deleted", record_id=record_id)
        return deleted

    async def list_records(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        kind_filter: list[MemoryKind] | None = None,
        status: list[LifecycleStatus] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List records with optional filters and pagination.

        ``status``: if provided, records are filtered to those whose ``status``
        column is in the given list (push-down filter). MTRNIX-314.
        ``kind_filter``: if provided, records are filtered to those whose
        ``kind`` column is in the given list. MTRNIX-275.
        """
        where_parts = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": workspace_id, "limit": limit, "offset": offset}

        if agent_id is not None:
            where_parts.append("agent_id = :agent_id")
            params["agent_id"] = agent_id
        if scope is not None:
            where_parts.append("scope = :scope")
            params["scope"] = scope.value
        if kind_filter is not None:
            where_parts.append("kind = ANY(:kind_list)")
            params["kind_list"] = [k.value for k in kind_filter]
        if status is not None:
            where_parts.append("status = ANY(:status_list)")
            params["status_list"] = [s.value for s in status]

        where_clause = " AND ".join(where_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_RECORD_COLUMNS}
                    FROM memory_records
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.fetchall()
        return [_row_to_record(r._mapping) for r in rows]

    async def count_records(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
        kind_filter: list[MemoryKind] | None = None,
        status: list[LifecycleStatus] | None = None,
    ) -> int:
        """Count memory records matching filters.

        ``status``: matches ``list_records`` — when provided, only rows whose
        ``status`` column is in the list are counted. MTRNIX-314.
        ``kind_filter``: matches ``list_records``. MTRNIX-275.
        """
        conditions = ["workspace_id = :workspace_id"]
        params: dict[str, Any] = {"workspace_id": workspace_id}
        if agent_id is not None:
            conditions.append("agent_id = :agent_id")
            params["agent_id"] = agent_id
        if scope is not None:
            conditions.append("scope = :scope")
            params["scope"] = scope.value
        if kind_filter is not None:
            conditions.append("kind = ANY(:kind_list)")
            params["kind_list"] = [k.value for k in kind_filter]
        if status is not None:
            conditions.append("status = ANY(:status_list)")
            params["status_list"] = [s.value for s in status]
        where = " AND ".join(conditions)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"SELECT count(*) FROM memory_records WHERE {where}"),
                params,
            )
            return result.scalar() or 0

    async def list_workspaces(self) -> list[str]:
        """Return distinct ``workspace_id`` values present in ``memory_records``.

        Used by the scheduled-scan safety net to enumerate workspaces
        without having to depend on a higher-level ``WorkspacesManager``
        (MTRNIX-316). Returns an empty list on PG failure? No — let the
        exception propagate so the caller can swallow+bump the scan-error
        counter (``ScheduledScan.run`` already does).
        """
        async with self._engine.begin() as conn:
            result = await conn.execute(text("SELECT DISTINCT workspace_id FROM memory_records"))
            rows = result.fetchall()
        return [str(row[0]) for row in rows]

    async def list_stale_candidates(
        self,
        workspace_id: str,
        *,
        older_than: datetime,
        limit: int = 500,
    ) -> list[str]:
        """Return ids of non-terminal records older than ``older_than`` (MTRNIX-316).

        Used by the scheduled-scan safety net to enqueue freshness jobs for
        memory records that never received a write-triggered event. Skips
        terminal statuses (``stale``, ``superseded``, ``archived``) so the
        pipeline does not re-process lifecycle-closed rows. Ordered ASC so
        the oldest rows run first.
        """
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT id
                    FROM memory_records
                    WHERE workspace_id = :ws
                      AND status NOT IN ('stale', 'superseded', 'archived')
                      AND updated_at < :older_than
                    ORDER BY updated_at ASC
                    LIMIT :limit
                    """
                ),
                {"ws": workspace_id, "older_than": older_than, "limit": limit},
            )
            rows = result.fetchall()
        return [str(row[0]) for row in rows]

    async def get_many_statuses(
        self, workspace_id: str, record_ids: list[str]
    ) -> dict[str, LifecycleStatus]:
        """Batch-fetch ``status`` for a set of record ids within a workspace.

        Missing ids are simply absent from the returned dict. Used by the
        hybrid memory search graph-leg post-filter (MTRNIX-314) — graph hits
        have no Qdrant payload, so status must be looked up from PG.
        """
        if not record_ids:
            return {}
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, status FROM memory_records "
                    "WHERE workspace_id = :ws AND id = ANY(:ids)"
                ),
                {"ws": workspace_id, "ids": list(record_ids)},
            )
            rows = result.fetchall()
        out: dict[str, LifecycleStatus] = {}
        for r in rows:
            try:
                out[r[0]] = LifecycleStatus(r[1])
            except ValueError:
                out[r[0]] = LifecycleStatus.ACTIVE
        return out

    async def update(
        self,
        workspace_id: str,
        record_id: str,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        importance_score: float | None = None,
        kind: MemoryKind | None = None,
    ) -> MemoryRecord | None:
        """Partial update of a memory record. Returns updated record or None.

        Uses UPDATE ... RETURNING to avoid an extra SELECT round-trip.
        """
        set_parts: list[str] = []
        params: dict[str, Any] = {"id": record_id, "ws": workspace_id}

        if content is not None:
            set_parts.append("content = :content")
            params["content"] = content
            set_parts.append("content_hash = :content_hash")
            params["content_hash"] = hashlib.sha256(content.encode()).hexdigest()
        if tags is not None:
            set_parts.append("tags = CAST(:tags AS jsonb)")
            params["tags"] = json.dumps(tags)
        if importance_score is not None:
            set_parts.append("importance_score = :importance_score")
            params["importance_score"] = importance_score
        if kind is not None:
            set_parts.append("kind = :kind")
            params["kind"] = kind.value

        if not set_parts:
            return await self.get(workspace_id, record_id)

        now = datetime.now(UTC)
        set_parts.append("updated_at = :updated_at")
        params["updated_at"] = now

        set_clause = ", ".join(set_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"UPDATE memory_records SET {set_clause} "
                    f"WHERE id = :id AND workspace_id = :ws "
                    f"RETURNING {_RECORD_COLUMNS}"
                ),
                params,
            )
            row = result.first()

        if row is None:
            return None

        return _row_to_record(row._mapping)

    async def update_lifecycle(
        self,
        workspace_id: str,
        record_id: str,
        *,
        status: MemoryStatus | None = None,
        freshness_score: float | None = None,
        superseded_by: str | None = None,
        evidence_count: int | None = None,
        verification_state: str | None = None,
        valid_until: datetime | None = None,
        append_tag: str | None = None,
        append_tags: list[str] | None = None,
        conn: AsyncConnection | None = None,
    ) -> MemoryRecord | None:
        """Freshness-pipeline partial update for lifecycle columns.

        Only supplied fields are written. Always bumps ``updated_at``. The
        ``append_tag`` helper lets Curator add a tag idempotently without
        having to round-trip the full record. ``append_tags`` is the batch
        variant used by the freshness DecisionEngine to merge N tags in a
        single UPDATE (no N+1); dedup happens in SQL so concurrent writers
        cannot race a read-modify-write.

        When ``conn`` is provided, the UPDATE runs on the caller-supplied
        connection so multiple writes can be grouped in one transaction
        (MTRNIX-319 fix). When ``conn`` is None, a self-managed transaction
        is used — the pre-MTRNIX-319 behaviour.
        """
        set_parts: list[str] = []
        params: dict[str, Any] = {"id": record_id, "ws": workspace_id}

        if status is not None:
            set_parts.append("status = :status")
            params["status"] = status.value
        if freshness_score is not None:
            set_parts.append("freshness_score = :freshness_score")
            params["freshness_score"] = freshness_score
        # ``superseded_by`` accepts None explicitly via a sentinel check; to
        # keep the API minimal, None here means "leave unchanged" — callers
        # that want to clear the link pass an empty string instead.
        if superseded_by is not None:
            if superseded_by == "":
                set_parts.append("superseded_by = NULL")
            else:
                set_parts.append("superseded_by = :superseded_by")
                params["superseded_by"] = superseded_by
        if evidence_count is not None:
            set_parts.append("evidence_count = :evidence_count")
            params["evidence_count"] = evidence_count
        if verification_state is not None:
            set_parts.append("verification_state = :verification_state")
            params["verification_state"] = verification_state
        if valid_until is not None:
            set_parts.append("valid_until = :valid_until")
            params["valid_until"] = valid_until
        if append_tag is not None:
            # Idempotent tag-append: only add when not already present.
            set_parts.append(
                "tags = CASE "
                "WHEN tags @> CAST(:tag_array AS jsonb) THEN tags "
                "ELSE tags || CAST(:tag_array AS jsonb) END"
            )
            params["tag_array"] = json.dumps([append_tag])
        if append_tags:
            # Batch idempotent append — dedup is done in SQL against the
            # current row's ``tags`` so concurrent Curator writes can't be
            # clobbered by a stale read-modify-write.
            set_parts.append(
                "tags = tags || COALESCE("
                "(SELECT jsonb_agg(e) "
                "FROM jsonb_array_elements_text(CAST(:new_tags AS jsonb)) AS e "
                "WHERE NOT tags @> jsonb_build_array(e)), "
                "'[]'::jsonb)"
            )
            # Dedup input list itself so we don't pass the same tag twice.
            seen: set[str] = set()
            unique_tags: list[str] = []
            for t in append_tags:
                if t not in seen:
                    seen.add(t)
                    unique_tags.append(t)
            params["new_tags"] = json.dumps(unique_tags)

        if not set_parts:
            return await self.get(workspace_id, record_id)

        set_parts.append("updated_at = :updated_at")
        params["updated_at"] = datetime.now(UTC)
        set_clause = ", ".join(set_parts)

        sql = text(
            f"UPDATE memory_records SET {set_clause} "
            f"WHERE id = :id AND workspace_id = :ws "
            f"RETURNING {_RECORD_COLUMNS}"
        )

        if conn is not None:
            result = await conn.execute(sql, params)
            row = result.first()
        else:
            async with self._engine.begin() as own_conn:
                result = await own_conn.execute(sql, params)
                row = result.first()

        if row is None:
            return None
        logger.debug(
            "memory_pg.lifecycle_updated",
            workspace_id=workspace_id,
            record_id=record_id,
            status=status.value if status else None,
        )
        return _row_to_record(row._mapping)

    async def reset(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
    ) -> tuple[int, list[str]]:
        """Bulk-delete matching records. Returns (count, deleted_ids).

        Uses DELETE ... RETURNING id inside a single transaction so the
        deleted-id set is authoritative (no race with concurrent inserts).
        """
        where_parts = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": workspace_id}

        if agent_id is not None:
            where_parts.append("agent_id = :agent_id")
            params["agent_id"] = agent_id
        if scope is not None:
            where_parts.append("scope = :scope")
            params["scope"] = scope.value

        where_clause = " AND ".join(where_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"DELETE FROM memory_records WHERE {where_clause} RETURNING id"),
                params,
            )
            rows = result.fetchall()
        ids = [r[0] for r in rows]
        count = len(ids)
        logger.info("memory_pg.reset", workspace_id=workspace_id, count=count)
        return count, ids

    # ------------------------------------------------------------------
    # Dedup + TTL
    # ------------------------------------------------------------------

    async def get_by_hash(
        self, workspace_id: str, agent_id: str, content_hash: str
    ) -> MemoryRecord | None:
        """Find a record by content hash within the same agent. Used for dedup."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_RECORD_COLUMNS}
                    FROM memory_records
                    WHERE workspace_id = :ws AND agent_id = :agent_id
                      AND content_hash = :hash
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"ws": workspace_id, "agent_id": agent_id, "hash": content_hash},
            )
            row = result.first()
        if row is None:
            return None
        return _row_to_record(row._mapping)

    async def delete_expired(self, workspace_id: str) -> int:
        """Delete records whose TTL has passed. Returns number removed."""
        now = datetime.now(UTC)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    DELETE FROM memory_records
                    WHERE workspace_id = :ws AND ttl_expires_at < :now
                """),
                {"ws": workspace_id, "now": now},
            )
            count = result.rowcount
        if count:
            logger.info("memory_pg.expired_deleted", workspace_id=workspace_id, count=count)
        return count

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def save_snapshot(self, snapshot: MemorySnapshot) -> MemorySnapshot:
        """Insert a snapshot metadata row."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(f"""
                    INSERT INTO memory_snapshots ({_SNAPSHOT_COLUMNS})
                    VALUES (:id, :workspace_id, :agent_id, :label, :trigger,
                            :record_count, :content_hash, :size_bytes,
                            :storage_path, :created_at)
                """),
                {
                    "id": snapshot.id,
                    "workspace_id": snapshot.workspace_id,
                    "agent_id": snapshot.agent_id,
                    "label": snapshot.label,
                    "trigger": snapshot.trigger,
                    "record_count": snapshot.record_count,
                    "content_hash": snapshot.content_hash,
                    "size_bytes": snapshot.size_bytes,
                    "storage_path": snapshot.storage_path,
                    "created_at": snapshot.created_at,
                },
            )
        logger.debug("memory_pg.snapshot_saved", snapshot_id=snapshot.id)
        return snapshot

    async def delete_snapshot(self, workspace_id: str, snapshot_id: str) -> bool:
        """Delete a snapshot. Returns True if it existed."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM memory_snapshots WHERE id = :id AND workspace_id = :ws"),
                {"id": snapshot_id, "ws": workspace_id},
            )
            deleted = result.rowcount > 0
        if deleted:
            logger.debug("memory_pg.snapshot_deleted", snapshot_id=snapshot_id)
        return deleted

    async def get_snapshot(self, workspace_id: str, snapshot_id: str) -> MemorySnapshot | None:
        """Fetch a snapshot by id."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_SNAPSHOT_COLUMNS}
                    FROM memory_snapshots
                    WHERE id = :id AND workspace_id = :ws
                """),
                {"id": snapshot_id, "ws": workspace_id},
            )
            row = result.first()
        if row is None:
            return None
        return _row_to_snapshot(row._mapping)

    async def list_snapshots(self, workspace_id: str, agent_id: str) -> list[MemorySnapshot]:
        """List snapshots for an agent, newest first."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT {_SNAPSHOT_COLUMNS}
                    FROM memory_snapshots
                    WHERE workspace_id = :ws AND agent_id = :agent_id
                    ORDER BY created_at DESC
                """),
                {"ws": workspace_id, "agent_id": agent_id},
            )
            rows = result.fetchall()
        return [_row_to_snapshot(r._mapping) for r in rows]
