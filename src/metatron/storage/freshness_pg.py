"""PostgreSQL store for freshness-pipeline audit artefacts.

Holds two tables created by migration 016 and extended by 018:

* ``review_entries`` — human-review items (duplicates, low-confidence
  decisions, contradictions) surfaced to the Control Center review queue
  (MTRNIX-314). Phase B (MTRNIX-313) renames ``record_id`` to ``target_id``
  and adds a ``target_kind`` discriminator so memory and KB review items
  share the table.
* ``machine_events`` — append-only audit log written by the freshness
  worker for every stage transition. Read by MCP ``memory_status``.

Workspace isolation is enforced at the API level: every public method takes
``workspace_id`` and every query filters on it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

from metatron.core.models import MachineEvent, ReviewEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = structlog.get_logger()


def _as_aware(value: Any) -> datetime | None:
    """Return a tz-aware UTC datetime or None."""
    if value is None:
        return None
    dt: datetime = value
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _row_to_review_entry(m: Any) -> ReviewEntry:
    # ``m`` is a SQLAlchemy RowMapping (dict-like). Support both ``__getitem__``
    # and ``.get`` on real rows, and tolerate fake dict-backed mocks used in
    # unit tests.
    try:
        target_kind = m["target_kind"]
    except (KeyError, TypeError):
        target_kind = "memory_record"
    return ReviewEntry(
        id=m["id"],
        workspace_id=m["workspace_id"],
        target_id=m["target_id"],
        target_kind=target_kind,
        # ``record_id`` is mirrored by ``ReviewEntry.__post_init__`` to
        # keep Phase A call sites working.
        reason=m["reason"],
        related_record_id=m["related_record_id"],
        content=m["content"],
        confidence=float(m["confidence"]),
        created_at=_as_aware(m["created_at"]) or datetime.now(UTC),
    )


def _row_to_machine_event(m: Any) -> MachineEvent:
    payload = m["payload"]
    if payload is None:
        payload_dict: dict[str, Any] = {}
    elif isinstance(payload, dict):
        payload_dict = payload
    else:
        payload_dict = json.loads(payload)
    return MachineEvent(
        id=m["id"],
        workspace_id=m["workspace_id"],
        event_type=m["event_type"],
        actor=m["actor"],
        target_kind=m["target_kind"],
        target_id=m["target_id"],
        payload=payload_dict,
        created_at=_as_aware(m["created_at"]) or datetime.now(UTC),
    )


class FreshnessStore:
    """Async PG store for ``review_entries`` and ``machine_events``.

    Phase B (MTRNIX-313): the table schema now carries a ``target_kind``
    discriminator and the former ``record_id`` column is renamed to
    ``target_id``. The Python API keeps ``record_id=`` as a keyword alias on
    :meth:`find_review_entry` / :meth:`list_review_entries` so Phase A call
    sites work unchanged.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # ReviewEntry
    # ------------------------------------------------------------------

    async def save_review_entry(self, entry: ReviewEntry) -> ReviewEntry:
        """Insert a review entry. Caller controls ``id`` (idempotent retries)."""
        # Pick up ``target_kind`` from the entry; Phase A dataclasses set it
        # to ``"memory_record"`` by default. ``target_id`` is mirrored from
        # ``record_id`` via ``ReviewEntry.__post_init__``.
        effective_target_id = entry.target_id or entry.record_id
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO review_entries (
                        id, workspace_id, target_kind, target_id, reason,
                        related_record_id, content, confidence, created_at
                    ) VALUES (
                        :id, :workspace_id, :target_kind, :target_id, :reason,
                        :related_record_id, :content, :confidence, :created_at
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": entry.id,
                    "workspace_id": entry.workspace_id,
                    "target_kind": entry.target_kind or "memory_record",
                    "target_id": effective_target_id,
                    "reason": entry.reason,
                    "related_record_id": entry.related_record_id,
                    "content": entry.content,
                    "confidence": entry.confidence,
                    "created_at": entry.created_at,
                },
            )
        logger.debug(
            "freshness_pg.review_saved",
            workspace_id=entry.workspace_id,
            target_id=effective_target_id,
            target_kind=entry.target_kind,
            reason=entry.reason,
        )
        return entry

    async def list_review_entries(
        self,
        workspace_id: str,
        *,
        record_id: str | None = None,
        target_id: str | None = None,
        target_kind: str | None = None,
        reason: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewEntry]:
        """List review entries for a workspace, optionally filtered.

        ``record_id`` is the Phase A keyword, kept as an alias for
        ``target_id``. If both are passed, ``target_id`` wins.

        MTRNIX-314 additions:
        * ``reason`` — filter by the review reason (e.g. ``possible_duplicate``).
        * ``offset`` — offset-based pagination.
        """
        effective_target_id = target_id if target_id is not None else record_id
        where_parts = ["workspace_id = :ws"]
        params: dict[str, Any] = {
            "ws": workspace_id,
            "limit": limit,
            "offset": offset,
        }
        if effective_target_id is not None:
            where_parts.append("target_id = :target_id")
            params["target_id"] = effective_target_id
        if target_kind is not None:
            where_parts.append("target_kind = :target_kind")
            params["target_kind"] = target_kind
        if reason is not None:
            where_parts.append("reason = :reason")
            params["reason"] = reason
        where_clause = " AND ".join(where_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT id, workspace_id, target_kind, target_id, reason,
                           related_record_id, content, confidence, created_at
                    FROM review_entries
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit
                    OFFSET :offset
                    """
                ),
                params,
            )
            rows = result.fetchall()
        return [_row_to_review_entry(r._mapping) for r in rows]

    async def count_review_entries(
        self,
        workspace_id: str,
        *,
        record_id: str | None = None,
        target_id: str | None = None,
        target_kind: str | None = None,
        reason: str | None = None,
    ) -> int:
        """Count review entries matching the same filters as ``list_review_entries``.

        Returns the total row count for UI pagination (independent of limit/offset).
        """
        effective_target_id = target_id if target_id is not None else record_id
        where_parts = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": workspace_id}
        if effective_target_id is not None:
            where_parts.append("target_id = :target_id")
            params["target_id"] = effective_target_id
        if target_kind is not None:
            where_parts.append("target_kind = :target_kind")
            params["target_kind"] = target_kind
        if reason is not None:
            where_parts.append("reason = :reason")
            params["reason"] = reason
        where_clause = " AND ".join(where_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT COUNT(*) FROM review_entries
                    WHERE {where_clause}
                    """
                ),
                params,
            )
            count = result.scalar()
        return int(count or 0)

    async def delete_review_entry(
        self,
        workspace_id: str,
        review_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> bool:
        """Delete a review entry by id, scoped to workspace.

        Returns ``True`` if a row was deleted, ``False`` if the id was missing
        (or the workspace did not match — cross-tenant deletes are a no-op).

        When ``conn`` is provided, the DELETE runs on the caller-supplied
        connection — used by ``MemoryService.resolve_review`` to group the
        update + delete + event-write into one transaction (MTRNIX-319 fix).
        """
        sql = text("DELETE FROM review_entries WHERE id = :id AND workspace_id = :ws")
        params = {"id": review_id, "ws": workspace_id}
        if conn is not None:
            result = await conn.execute(sql, params)
            return bool(result.rowcount and result.rowcount > 0)
        async with self._engine.begin() as own_conn:
            result = await own_conn.execute(sql, params)
            return bool(result.rowcount and result.rowcount > 0)

    async def find_review_entry(
        self,
        workspace_id: str,
        *,
        record_id: str | None = None,
        target_id: str | None = None,
        target_kind: str = "memory_record",
        reason: str,
        related_record_id: str | None = None,
    ) -> ReviewEntry | None:
        """Lookup helper so stages stay idempotent (e.g. Reconciler rerun).

        ``record_id`` kept as Phase A alias for ``target_id``.
        """
        effective_target_id = target_id if target_id is not None else record_id
        if effective_target_id is None:
            raise ValueError("find_review_entry requires target_id or record_id")
        params: dict[str, Any] = {
            "ws": workspace_id,
            "target_id": effective_target_id,
            "target_kind": target_kind,
            "reason": reason,
        }
        where_parts = [
            "workspace_id = :ws",
            "target_id = :target_id",
            "target_kind = :target_kind",
            "reason = :reason",
        ]
        if related_record_id is None:
            where_parts.append("related_record_id IS NULL")
        else:
            where_parts.append("related_record_id = :related_record_id")
            params["related_record_id"] = related_record_id
        where_clause = " AND ".join(where_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT id, workspace_id, target_kind, target_id, reason,
                           related_record_id, content, confidence, created_at
                    FROM review_entries
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                params,
            )
            row = result.first()
        if row is None:
            return None
        return _row_to_review_entry(row._mapping)

    # ------------------------------------------------------------------
    # MachineEvent
    # ------------------------------------------------------------------

    async def save_machine_event(
        self,
        event: MachineEvent,
        *,
        conn: AsyncConnection | None = None,
    ) -> MachineEvent:
        """Append a machine event — retries are safe via PK conflict.

        When ``conn`` is provided, the INSERT runs on the caller-supplied
        connection so it can be grouped with other writes in a single
        transaction (MTRNIX-319 fix).
        """
        sql = text(
            """
            INSERT INTO machine_events (
                id, workspace_id, event_type, actor, target_kind,
                target_id, payload, created_at
            ) VALUES (
                :id, :workspace_id, :event_type, :actor, :target_kind,
                :target_id, CAST(:payload AS jsonb), :created_at
            )
            ON CONFLICT (id) DO NOTHING
            """
        )
        params = {
            "id": event.id,
            "workspace_id": event.workspace_id,
            "event_type": event.event_type,
            "actor": event.actor,
            "target_kind": event.target_kind,
            "target_id": event.target_id,
            "payload": json.dumps(event.payload, default=str),
            "created_at": event.created_at,
        }
        if conn is not None:
            await conn.execute(sql, params)
        else:
            async with self._engine.begin() as own_conn:
                await own_conn.execute(sql, params)
        return event

    async def list_events_for_target(
        self,
        workspace_id: str,
        target_kind: str,
        target_id: str,
        *,
        limit: int = 100,
    ) -> list[MachineEvent]:
        """List events for a specific target within a workspace."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT id, workspace_id, event_type, actor, target_kind,
                           target_id, payload, created_at
                    FROM machine_events
                    WHERE workspace_id = :ws
                      AND target_kind = :target_kind
                      AND target_id = :target_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "ws": workspace_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "limit": limit,
                },
            )
            rows = result.fetchall()
        return [_row_to_machine_event(r._mapping) for r in rows]


# Backward compatibility for Phase A callers (MTRNIX-304).
FreshnessPostgresStore = FreshnessStore
