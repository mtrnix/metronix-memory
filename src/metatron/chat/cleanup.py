"""ChatHistoryCleanupWorker — cron process for retention-based message pruning (MTRNIX-353, T3).

Run as: ``python -m metatron.chat``

The worker operates in two stages per pass:
1. Delete messages older than the retention cutoff.
2. Delete orphan threads (no messages, older than the cutoff).

Both stages return row counts logged at INFO level. Exceptions are caught and
logged at WARNING; the worker continues to the next pass after applying
exponential backoff.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from metatron.chat.persistence import ChatPersistence  # noqa: TC001 — constructor parameter

logger = structlog.get_logger(__name__)


@dataclass
class ChatCleanupStats:
    """Counts from a single cleanup pass."""

    messages_deleted: int
    threads_deleted: int


class ChatHistoryCleanupWorker:
    """Bounded-error loop that prunes old chat messages and orphan threads.

    Parameters
    ----------
    persistence:
        Injected DAO — no global state.
    retention_days:
        Messages older than this many days are eligible for deletion.
    interval_seconds:
        Sleep interval between successful passes.
    """

    def __init__(
        self,
        persistence: ChatPersistence,
        *,
        retention_days: int,
        interval_seconds: int,
    ) -> None:
        self._persistence = persistence
        self._retention_days = retention_days
        self._interval_seconds = interval_seconds

    async def run_once(self) -> ChatCleanupStats:
        """Execute one cleanup pass.

        Returns zero stats on error (does not re-raise).
        """
        try:
            cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)
            messages_deleted = await self._persistence.delete_messages_older_than(cutoff)
            threads_deleted = await self._persistence.delete_orphan_threads(cutoff)
            logger.info(
                "chat.cleanup.pass",
                messages_deleted=messages_deleted,
                threads_deleted=threads_deleted,
                retention_days=self._retention_days,
            )
            return ChatCleanupStats(
                messages_deleted=messages_deleted,
                threads_deleted=threads_deleted,
            )
        except Exception as exc:
            logger.warning("chat.cleanup.error", error=str(exc), exc_info=True)
            return ChatCleanupStats(messages_deleted=0, threads_deleted=0)

    async def run_forever(self) -> None:
        """Run cleanup passes indefinitely with error-bounded exponential backoff.

        Exits cleanly on :class:`asyncio.CancelledError`.
        """
        _backoff_base = 2.0
        _backoff_cap = 60.0
        consecutive_errors = 0

        logger.info(
            "chat.cleanup.worker.started",
            retention_days=self._retention_days,
            interval_seconds=self._interval_seconds,
        )
        while True:
            try:
                await self.run_once()
                consecutive_errors = 0
                await asyncio.sleep(self._interval_seconds)
            except asyncio.CancelledError:
                logger.info("chat.cleanup.worker.cancelled")
                return
            except Exception as exc:
                consecutive_errors += 1
                backoff = min(
                    _backoff_base * (2 ** (consecutive_errors - 1)),
                    _backoff_cap,
                )
                logger.warning(
                    "chat.cleanup.worker.error",
                    consecutive_errors=consecutive_errors,
                    backoff_seconds=backoff,
                    error=str(exc),
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    logger.info("chat.cleanup.worker.cancelled")
                    return
