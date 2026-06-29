"""ActivityLogger — EventBus subscriber that writes to agent_activity_log.

Maps well-known EventBus topics to ``event_type`` strings and projects each
payload to the narrow shape documented in the spec. If neither the payload
nor the contextvar carries an ``agent_id``, the event is dropped with a
structlog warning (per spec: events without an owner are not persisted).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from metronix.activity.context import current_agent_id
from metronix.core.events import (
    AGENT_CREATED,
    AGENT_DELETED,
    AGENT_STATUS_CHANGED,
    AGENT_UPDATED,
    DOCUMENT_ACCESSED,
    ERROR_OCCURRED,
    MEMORY_DELETED,
    MEMORY_PROMOTED,
    MEMORY_RESET,
    MEMORY_STORED,
    QUERY_EXECUTED,
    TOOL_CALLED,
    EventBus,
)
from metronix.storage.activity_pg import ActivityRow

if TYPE_CHECKING:
    from metronix.storage.activity_pg import ActivityStore

logger = structlog.get_logger(__name__)


# EventBus topic -> event_type string written to the activity log.
_EVENT_TYPE_BY_TOPIC: dict[str, str] = {
    MEMORY_STORED: "memory.created",
    MEMORY_DELETED: "memory.deleted",
    MEMORY_RESET: "memory.reset",
    MEMORY_PROMOTED: "memory.promoted",
    QUERY_EXECUTED: "query.processed",
    DOCUMENT_ACCESSED: "document.accessed",
    TOOL_CALLED: "tool.called",
    AGENT_CREATED: "agent.created",
    AGENT_UPDATED: "agent.updated",
    AGENT_STATUS_CHANGED: "agent.status_changed",
    AGENT_DELETED: "agent.deleted",
    ERROR_OCCURRED: "error",
}

# Keys that live as table columns — must not be duplicated in event_data.
_RESERVED = frozenset({"workspace_id", "agent_id", "session_id"})


class ActivityLogger:
    """Bridges EventBus events to the activity-log store."""

    def __init__(self, store: ActivityStore) -> None:
        self._store = store

    def subscribe(self, bus: EventBus) -> None:
        for topic in _EVENT_TYPE_BY_TOPIC:
            bus.subscribe(topic, self._handle_event)

    async def _handle_event(self, event_name: str, payload: dict[str, Any]) -> None:
        event_type = _EVENT_TYPE_BY_TOPIC.get(event_name)
        if event_type is None:  # pragma: no cover — only subscribed topics land here
            return

        workspace_id = payload.get("workspace_id")
        if not workspace_id:
            logger.warning(
                "activity_log.skipped_no_workspace_id",
                event_type=event_type,
                topic=event_name,
            )
            return

        agent_id = payload.get("agent_id") or current_agent_id.get()
        if not agent_id:
            logger.info(
                "activity_log.skipped_no_agent_id",
                event_type=event_type,
                topic=event_name,
                workspace_id=workspace_id,
            )
            return

        session_id = payload.get("session_id")
        event_data = {k: v for k, v in payload.items() if k not in _RESERVED}

        row = ActivityRow(
            workspace_id=str(workspace_id),
            agent_id=str(agent_id),
            session_id=str(session_id) if session_id else None,
            event_type=event_type,
            event_data=event_data,
        )
        try:
            await self._store.insert(row)
        except Exception as exc:  # noqa: BLE001 — log DB failures without re-raising
            logger.error(
                "activity_log.insert_failed",
                event_type=event_type,
                error=str(exc),
                exc_info=True,
            )
