"""Best-effort expiry worker for temporary conversation event content."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from metronix.storage.conversation_postgres import ConversationPostgresStore

logger = structlog.get_logger(__name__)


class ConversationExpiryWorker:
    """Removes expired temporary events while retaining durable ledgers."""

    def __init__(self, events: ConversationPostgresStore, *, interval_seconds: int) -> None:
        self._events = events
        self._interval_seconds = max(60, interval_seconds)

    async def run_forever(self) -> None:
        while True:
            await self.sweep_once()
            await asyncio.sleep(self._interval_seconds)

    async def sweep_once(self) -> int:
        try:
            deleted_count = await self._events.expire_events(older_than=datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 — maintenance must never stop the API
            logger.warning("conversation.expiry.failed", error_type=type(exc).__name__)
            return 0
        logger.info("conversation.expiry.completed", expired_event_count=deleted_count)
        return deleted_count
