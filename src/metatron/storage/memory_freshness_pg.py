"""PostgreSQL store for freshness-pipeline audit artefacts (MTRNIX-304).

Holds two tables created by migration 016:

* ``review_entries`` — human-review items (duplicates, low-confidence
  decisions, contradictions) that should surface in the Control Center
  review queue once MTRNIX-314 ships.
* ``machine_events`` — append-only audit log written by the freshness
  worker for every stage transition. Read by MCP ``memory_status`` in
  MTRNIX-314.

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
    from sqlalchemy.ext.asyncio import AsyncEngine

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
    return ReviewEntry(
        id=m["id"],
        workspace_id=m["workspace_id"],
        record_id=m["record_id"],
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


class FreshnessPostgresStore:
    """Async PG store for ``review_entries`` and ``machine_events``."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # ReviewEntry
    # ------------------------------------------------------------------

    async def save_review_entry(self, entry: ReviewEntry) -> ReviewEntry:
        """Insert a review entry. Caller controls ``id`` (idempotent retries)."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO review_entries (
                        id, workspace_id, record_id, reason, related_record_id,
                        content, confidence, created_at
                    ) VALUES (
                        :id, :workspace_id, :record_id, :reason, :related_record_id,
                        :content, :confidence, :created_at
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": entry.id,
                    "workspace_id": entry.workspace_id,
                    "record_id": entry.record_id,
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
            record_id=entry.record_id,
            reason=entry.reason,
        )
        return entry

    async def list_review_entries(
        self,
        workspace_id: str,
        *,
        record_id: str | None = None,
        limit: int = 100,
    ) -> list[ReviewEntry]:
        """List review entries for a workspace, optionally filtered by record."""
        where_parts = ["workspace_id = :ws"]
        params: dict[str, Any] = {"ws": workspace_id, "limit": limit}
        if record_id is not None:
            where_parts.append("record_id = :record_id")
            params["record_id"] = record_id
        where_clause = " AND ".join(where_parts)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT id, workspace_id, record_id, reason, related_record_id,
                           content, confidence, created_at
                    FROM review_entries
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
            rows = result.fetchall()
        return [_row_to_review_entry(r._mapping) for r in rows]

    async def find_review_entry(
        self,
        workspace_id: str,
        *,
        record_id: str,
        reason: str,
        related_record_id: str | None = None,
    ) -> ReviewEntry | None:
        """Lookup helper so stages stay idempotent (e.g. Reconciler rerun)."""
        params: dict[str, Any] = {
            "ws": workspace_id,
            "record_id": record_id,
            "reason": reason,
        }
        where_parts = [
            "workspace_id = :ws",
            "record_id = :record_id",
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
                    SELECT id, workspace_id, record_id, reason, related_record_id,
                           content, confidence, created_at
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

    async def save_machine_event(self, event: MachineEvent) -> MachineEvent:
        """Append a machine event — retries are safe via PK conflict."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
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
                ),
                {
                    "id": event.id,
                    "workspace_id": event.workspace_id,
                    "event_type": event.event_type,
                    "actor": event.actor,
                    "target_kind": event.target_kind,
                    "target_id": event.target_id,
                    "payload": json.dumps(event.payload, default=str),
                    "created_at": event.created_at,
                },
            )
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
