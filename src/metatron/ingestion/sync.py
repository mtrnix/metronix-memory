"""Background synchronization manager for periodic document updates.

Runs scheduled syncs from configured sources (Confluence, Jira, Notion, etc.)
and tracks document versions with temporal history.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Callable

import structlog

logger = structlog.get_logger(__name__)


class BackgroundSyncManager:
    """Manages background synchronization of documents from configured sources.
    
    Runs periodic syncs at configurable intervals and tracks document versions
    with temporal history for audit trails and historical queries.
    """

    def __init__(
        self,
        sync_interval_seconds: int = 3600,
        sources: list[str] | None = None,
    ):
        """Initialize BackgroundSyncManager.
        
        Args:
            sync_interval_seconds: Interval between syncs in seconds (default 1 hour).
            sources: List of source types to sync (confluence, jira, notion, etc.).
        """
        self.sync_interval = sync_interval_seconds
        self.sources = sources or ["confluence", "jira", "notion"]
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._sync_callbacks: dict[str, Callable] = {}

    def register_sync_callback(self, source: str, callback: Callable) -> None:
        """Register a callback to perform sync for a source.
        
        Args:
            source: Source name (e.g., 'confluence').
            callback: Async callable that performs the sync.
        """
        self._sync_callbacks[source] = callback
        logger.info("registered_sync_callback", source=source)

    async def start(self) -> None:
        """Start the background sync task.
        
        Starts the async loop that runs syncs at regular intervals.
        Safe to call multiple times — ignores if already running.
        """
        if self._running:
            logger.warning("BackgroundSyncManager already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(
            "BackgroundSyncManager started",
            interval_seconds=self.sync_interval,
            sources=self.sources,
        )

    async def stop(self) -> None:
        """Stop the background sync task.
        
        Cancels the sync loop and waits for it to terminate.
        Safe to call multiple times — ignores if not running.
        """
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("BackgroundSyncManager stopped")

    async def _sync_loop(self) -> None:
        """Run sync loop indefinitely.
        
        Sleeps for sync_interval, then runs sync_all_sources().
        Handles errors gracefully without stopping the loop.
        """
        while self._running:
            try:
                await asyncio.sleep(self.sync_interval)
                if self._running:
                    await self.sync_all_sources()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "sync_loop error",
                    error=str(exc),
                    exc_info=exc,
                )

    async def sync_all_sources(self) -> None:
        """Sync all configured sources.
        
        Runs each source sync in sequence. Failures in one source
        do not prevent syncing other sources.
        """
        logger.info("starting scheduled sync", sources=self.sources)

        sync_started = datetime.now(UTC)
        results: dict[str, dict[str, object]] = {}

        for source in self.sources:
            try:
                result = await self._sync_source(source)
                results[source] = {
                    "status": "success",
                    "result": result,
                }
                logger.info("sync completed", source=source)
            except Exception as exc:
                logger.error(
                    "sync failed",
                    source=source,
                    error=str(exc),
                    exc_info=exc,
                )
                results[source] = {
                    "status": "error",
                    "error": str(exc),
                }

        sync_ended = datetime.now(UTC)
        duration_ms = (sync_ended - sync_started).total_seconds() * 1000

        logger.info(
            "scheduled sync completed",
            duration_ms=duration_ms,
            results=results,
        )

    async def _sync_source(self, source: str) -> dict[str, object]:
        """Sync a single source.
        
        Delegates to registered callback if available,
        otherwise logs warning and returns.
        
        Args:
            source: Source name to sync.
        
        Returns:
            Result dict from sync operation.
        """
        if source not in self._sync_callbacks:
            logger.warning("no sync callback registered", source=source)
            return {"source": source, "status": "no_callback"}

        callback = self._sync_callbacks[source]
        result = await callback(source)
        return result
