"""In-process async event bus for plugin hooks.

Core emits named events; plugins subscribe handlers via PluginManager.
Handlers are called sequentially. A failing handler is logged and skipped —
it never blocks remaining handlers or the calling pipeline.

Usage (core emitting):
    bus = app.state.plugin_manager.get_event_bus()
    await bus.emit(DOCUMENT_INDEXED, {"doc_id": doc.id, "workspace_id": ws})

Usage (plugin subscribing):
    manager.register_event_handler(QUERY_EXECUTED, my_handler)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Well-known event name constants — use these instead of raw strings
# ---------------------------------------------------------------------------

DOCUMENT_INDEXED = "document_indexed"
CHUNK_CREATED = "chunk_created"
QUERY_EXECUTED = "query_executed"
USER_AUTHENTICATED = "user_authenticated"
USER_CREATED = "user_created"
SYNC_STARTED = "sync_started"
SYNC_COMPLETED = "sync_completed"
SYNC_FAILED = "sync_failed"

# Agent memory events (WS1)
# Payload conventions:
#   memory_stored            -> {"workspace_id", "agent_id", "record_id", "scope"}
#   memory_deleted           -> {"workspace_id", "agent_id", "record_id"}
#   memory_reset             -> {"workspace_id", "agent_id", "scope", "count"}
#   memory_snapshot_created  -> {"workspace_id", "agent_id", "snapshot_id",
#                                "trigger", "record_count"}
#   memory_restored          -> {"workspace_id", "agent_id", "snapshot_id",
#                                "record_count", "pre_restore_snapshot_id"}
MEMORY_STORED = "memory_stored"
MEMORY_DELETED = "memory_deleted"
MEMORY_RESET = "memory_reset"
MEMORY_SNAPSHOT_CREATED = "memory_snapshot_created"
MEMORY_RESTORED = "memory_restored"

# Freshness events (MTRNIX-304)
# Payload conventions:
#   freshness_job_enqueued     -> {"workspace_id", "record_id", "event_type"}
#   freshness_job_processed    -> {"workspace_id", "record_id", "decision_action",
#                                  "duration_ms"}
#   freshness_decision_applied -> {"workspace_id", "record_id", "action", "confidence"}
#   freshness_review_created   -> {"workspace_id", "record_id", "reason",
#                                  "review_entry_id"}
#   freshness_review_resolved  -> {"workspace_id", "target_kind", "target_id",
#                                  "review_entry_id", "action",
#                                  "old_status", "new_status"}
FRESHNESS_JOB_ENQUEUED = "freshness_job_enqueued"
FRESHNESS_JOB_PROCESSED = "freshness_job_processed"
FRESHNESS_DECISION_APPLIED = "freshness_decision_applied"
FRESHNESS_REVIEW_CREATED = "freshness_review_created"
FRESHNESS_REVIEW_RESOLVED = "freshness_review_resolved"

# Extended payload convention for QUERY_EXECUTED (existing constant, extended by WS4 S6):
#   query_executed         -> {"workspace_id", "agent_id", "session_id",
#                              "correlation_id", "query", "top_k",
#                              "result_count", "duration_ms", "source"}

# Agent activity events (WS4 S6 — activity logging)
# Payload conventions:
#   memory_promoted        -> {"workspace_id", "agent_id", "record_id",
#                              "from_scope", "to_scope"}
#   document_accessed      -> {"workspace_id", "agent_id", "session_id",
#                              "correlation_id", "document_ids", "channel"}
#   tool_called            -> {"workspace_id", "agent_id", "session_id",
#                              "tool_name", "arguments", "arguments_truncated",
#                              "duration_ms", "success", "error_message"}
#   agent_created          -> {"workspace_id", "agent_id", "config_version",
#                              "created_by"}
#   agent_updated          -> {"workspace_id", "agent_id", "config_version",
#                              "changed_by", "changed_fields"}
#   agent_status_changed   -> {"workspace_id", "agent_id", "old_status",
#                              "new_status", "changed_by"}
#   agent_deleted          -> {"workspace_id", "agent_id", "changed_by"}
#   error_occurred         -> {"workspace_id", "agent_id", "session_id",
#                              "source", "error_type", "error_message",
#                              "context"}
MEMORY_PROMOTED = "memory_promoted"
DOCUMENT_ACCESSED = "document_accessed"
TOOL_CALLED = "tool_called"
AGENT_CREATED = "agent_created"
AGENT_UPDATED = "agent_updated"
AGENT_STATUS_CHANGED = "agent_status_changed"
AGENT_DELETED = "agent_deleted"
ERROR_OCCURRED = "error_occurred"

# Type alias for async event handler callables
EventHandlerCallable = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """Async publish/subscribe bus for in-process events.

    Handlers are registered per event name and invoked on emit().
    All handler failures are isolated — one bad handler never crashes others.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandlerCallable]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandlerCallable) -> None:
        """Register an async handler for a named event.

        Args:
            event_name: Event to subscribe to. Use the module-level constants.
            handler: Async callable with signature (event_name: str, payload: dict) -> None.
        """
        self._handlers[event_name].append(handler)
        logger.debug(
            "event_bus.subscribed",
            event_name=event_name,
            handler=getattr(handler, "__qualname__", repr(handler)),
        )

    async def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        """Emit an event, invoking all registered handlers.

        Handlers are called in registration order. A failing handler is logged
        and skipped — remaining handlers still run.

        Args:
            event_name: Name of the event.
            payload: Arbitrary event data passed to each handler.
        """
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return

        logger.debug("event_bus.emit", event_name=event_name, handler_count=len(handlers))
        for handler in handlers:
            try:
                await handler(event_name, payload)
            except Exception as exc:
                logger.error(
                    "event_bus.handler_failed",
                    event_name=event_name,
                    handler=getattr(handler, "__qualname__", repr(handler)),
                    error=str(exc),
                    exc_info=True,
                )

    def handler_count(self, event_name: str) -> int:
        """Return the number of handlers registered for an event."""
        return len(self._handlers.get(event_name, []))

    def clear(self, event_name: str | None = None) -> None:
        """Remove handlers. Clears all events if event_name is None.

        Primarily useful in tests to reset state between test cases.
        """
        if event_name is None:
            self._handlers.clear()
        else:
            self._handlers.pop(event_name, None)
