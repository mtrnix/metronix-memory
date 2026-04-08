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
#   memory_snapshot_created  -> {"workspace_id", "agent_id", "snapshot_id", "trigger"}
#   memory_restored          -> {"workspace_id", "agent_id", "snapshot_id", "count"}
MEMORY_STORED = "memory_stored"
MEMORY_DELETED = "memory_deleted"
MEMORY_RESET = "memory_reset"
MEMORY_SNAPSHOT_CREATED = "memory_snapshot_created"
MEMORY_RESTORED = "memory_restored"

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
