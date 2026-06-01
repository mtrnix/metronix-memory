"""Best-effort writer for proxy.* activity rows (MTRNIX-372)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from metatron.storage.activity_pg import ActivityRow

if TYPE_CHECKING:
    from metatron.storage.activity_pg import ActivityStore

logger = structlog.get_logger(__name__)


class ProxyActivityLogger:
    """Writes proxy.* events to agent_activity_log with a correlation_id."""

    def __init__(self, *, store: ActivityStore | None, workspace_id: str) -> None:
        self._store = store
        self._workspace_id = workspace_id

    async def log(
        self,
        *,
        agent_id: str,
        event_type: str,
        correlation_id: str,
        data: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        if self._store is None:
            return
        row = ActivityRow(
            workspace_id=self._workspace_id,
            agent_id=agent_id,
            session_id=session_id,
            event_type=event_type,
            event_data=data,
            correlation_id=correlation_id,
        )
        try:
            await self._store.insert(row)
        except Exception as exc:  # noqa: BLE001 — never break the request
            logger.warning("proxy_activity.insert_failed", event_type=event_type, error=str(exc))
