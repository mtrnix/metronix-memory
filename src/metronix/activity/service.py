"""Read-side façade for /api/v1/agents/{id}/activity routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from metronix.storage.activity_pg import ActivityStore


_ALLOWED_PERIODS: dict[str, timedelta] = {
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


class ActivityService:
    """Thin facade over ``ActivityStore`` for the read endpoints."""

    def __init__(self, *, store: ActivityStore, workspace_id: str) -> None:
        self._store = store
        self._workspace_id = workspace_id

    async def list_for_agent(
        self,
        *,
        agent_id: str,
        since: datetime | None,
        until: datetime | None,
        event_types: list[str] | None,
        session_id: str | None,
        correlation_id: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return (events, has_more). Caller ensures agent belongs to workspace."""
        rows = await self._store.list_for_agent(
            workspace_id=self._workspace_id,
            agent_id=agent_id,
            since=since,
            until=until,
            event_types=event_types,
            session_id=session_id,
            correlation_id=correlation_id,
            limit=limit + 1,
            offset=offset,
        )
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def summary_for_agent(
        self,
        *,
        agent_id: str,
        period: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        delta = _ALLOWED_PERIODS.get(period)
        if delta is None:
            msg = f"invalid period: {period!r} (allowed: 1d, 7d, 30d, 90d)"
            raise ValueError(msg)

        until = now or datetime.now(UTC)
        since = until - delta
        out = await self._store.summary_for_agent(
            workspace_id=self._workspace_id,
            agent_id=agent_id,
            since=since,
            until=until,
        )
        return {
            "period": period,
            "since": since.isoformat(),
            "until": until.isoformat(),
            **out,
        }
