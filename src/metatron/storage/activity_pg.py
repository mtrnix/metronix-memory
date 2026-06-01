"""PostgreSQL store for agent_activity_log (WS4 S6).

Append-only by convention. `insert` never updates. No delete/update methods
are provided — retention is deferred to a later stage (see spec non-goals).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ActivityRow:
    workspace_id: str
    agent_id: str
    event_type: str
    event_data: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None  # server default when None


class ActivityStore:
    """Async access to ``agent_activity_log``. Thin — service layer composes."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def insert(self, row: ActivityRow) -> None:
        sql = text(
            """
            INSERT INTO agent_activity_log
                (workspace_id, agent_id, session_id, event_type, event_data,
                 correlation_id)
            VALUES
                (:workspace_id, :agent_id, :session_id, :event_type,
                 CAST(:event_data AS JSONB), :correlation_id)
            """
        )
        params = {
            "workspace_id": row.workspace_id,
            "agent_id": row.agent_id,
            "session_id": row.session_id,
            "event_type": row.event_type,
            "event_data": json.dumps(row.event_data),
            "correlation_id": row.correlation_id,
        }
        async with self._engine.begin() as conn:
            await conn.execute(sql, params)

    async def list_for_agent(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        since: datetime | None,
        until: datetime | None,
        event_types: list[str] | None,
        session_id: str | None,
        correlation_id: str | None = None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        where_parts = ["workspace_id = :workspace_id", "agent_id = :agent_id"]
        params: dict[str, Any] = {
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "limit": limit,
            "offset": offset,
        }
        if since is not None:
            where_parts.append("created_at >= :since")
            params["since"] = since
        if until is not None:
            where_parts.append("created_at < :until")
            params["until"] = until
        if event_types:
            where_parts.append("event_type = ANY(:event_types)")
            params["event_types"] = list(event_types)
        if session_id is not None:
            where_parts.append("session_id = :session_id")
            params["session_id"] = session_id
        if correlation_id is not None:
            where_parts.append("correlation_id = :correlation_id")
            params["correlation_id"] = correlation_id

        sql = text(
            f"""
            SELECT id, workspace_id, agent_id, session_id, event_type,
                   event_data, correlation_id, created_at
            FROM agent_activity_log
            WHERE {" AND ".join(where_parts)}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, params)
            return [dict(m) for m in result.mappings().all()]

    async def summary_for_agent(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        since: datetime,
        until: datetime,
    ) -> dict[str, Any]:
        """Counts by event_type and zero-filled daily counts."""
        per_type_sql = text(
            """
            SELECT event_type, COUNT(*) AS n
            FROM agent_activity_log
            WHERE workspace_id = :ws AND agent_id = :ag
              AND created_at >= :since AND created_at < :until
            GROUP BY event_type
            """
        )
        per_day_sql = text(
            """
            SELECT DATE(created_at AT TIME ZONE 'UTC') AS day, COUNT(*) AS n
            FROM agent_activity_log
            WHERE workspace_id = :ws AND agent_id = :ag
              AND created_at >= :since AND created_at < :until
            GROUP BY day
            ORDER BY day
            """
        )
        params = {"ws": workspace_id, "ag": agent_id, "since": since, "until": until}
        async with self._engine.begin() as conn:
            a = await conn.execute(per_type_sql, params)
            b = await conn.execute(per_day_sql, params)
            counts_by_type = {m["event_type"]: int(m["n"]) for m in a.mappings().all()}
            day_counts = {str(m["day"]): int(m["n"]) for m in b.mappings().all()}

        # Zero-fill days between since and until (UTC calendar days).
        # `until` is treated as exclusive — subtracting 1 µs ensures that a
        # midnight boundary like `until=2026-04-23T00:00Z` does NOT include
        # April 23rd in the buckets (which would be wrong for a 1d window
        # whose `since` lands on 2026-04-22T00:00Z).
        start_day = since.astimezone(UTC).date()
        end_day = (until.astimezone(UTC) - timedelta(microseconds=1)).date()
        days: list[dict[str, Any]] = []
        cursor: date = start_day
        while cursor <= end_day:
            key = cursor.isoformat()
            days.append({"date": key, "total": day_counts.get(key, 0)})
            cursor = cursor + timedelta(days=1)

        total = sum(counts_by_type.values())
        return {
            "total_events": total,
            "counts_by_event_type": counts_by_type,
            "counts_by_day": days,
        }
