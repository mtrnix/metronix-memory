"""PostgreSQL store for Agent Memory (WS1).

Source of truth for memory records and snapshots. Stores all fields
including content (unlike Neo4j which is metadata-only).

Uses raw SQL via SQLAlchemy async engine — same pattern as postgres.py.
This is an L1 storage module — no business logic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

from metatron.core.models import MemoryRecord, MemoryScope, MemorySnapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger()

# ------------------------------------------------------------------
# Row → dataclass helpers
# ------------------------------------------------------------------

_RECORD_COLUMNS = (
    "id, workspace_id, agent_id, scope, source_type, content, "
    "tags, importance_score, ttl_expires_at, content_hash, "
    "session_id, metadata, created_at, updated_at"
)

_SNAPSHOT_COLUMNS = (
    "id, workspace_id, agent_id, label, trigger, record_count, "
    "content_hash, size_bytes, storage_path, created_at"
)


def _row_to_record(m: Any) -> MemoryRecord:
    """Convert a DB row mapping to MemoryRecord."""
    ttl = m["ttl_expires_at"]
    if ttl and not getattr(ttl, "tzinfo", None):
        ttl = ttl.replace(tzinfo=UTC)
    created = m["created_at"]
    if created and not getattr(created, "tzinfo", None):
        created = created.replace(tzinfo=UTC)
    return MemoryRecord(
        id=m["id"],
        workspace_id=m["workspace_id"],
        agent_id=m["agent_id"],
        scope=MemoryScope(m["scope"]),
        source_type=m["source_type"],
        content=m["content"],
        tags=m["tags"] if isinstance(m["tags"], list) else json.loads(m["tags"]),
        importance_score=m["importance_score"],
        ttl_expires_at=ttl,
        content_hash=m["content_hash"],
        session_id=m["session_id"],
        metadata=(m["metadata"] if isinstance(m["metadata"], dict) else json.loads(m["metadata"])),
        created_at=created or datetime.now(UTC),
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
                    INSERT INTO memory_records ({_RECORD_COLUMNS})
                    VALUES (:id, :workspace_id, :agent_id, :scope, :source_type,
                            :content, :tags::jsonb, :importance_score, :ttl_expires_at,
                            :content_hash, :session_id, :metadata::jsonb,
                            :created_at, :updated_at)
                    ON CONFLICT (id) DO UPDATE SET
                        scope = EXCLUDED.scope,
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
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List records with optional filters and pagination."""
        where_parts = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": workspace_id, "limit": limit, "offset": offset}

        if agent_id is not None:
            where_parts.append("agent_id = :agent_id")
            params["agent_id"] = agent_id
        if scope is not None:
            where_parts.append("scope = :scope")
            params["scope"] = scope.value

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
