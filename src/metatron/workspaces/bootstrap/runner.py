"""BootstrapRunner — in-process task manager for concurrent workspace bootstrapping (T2).

Lives on ``app.state.bootstrap_runner``.  Manages a dict of in-flight
``asyncio.Task`` objects keyed by ``workspace_id``.  Thread-safety within
a single event loop is guaranteed by the ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from metatron.core.config import Settings
    from metatron.core.interfaces import ConnectorInterface
    from metatron.storage.bootstrap_state import BootstrapStateStore

logger = structlog.get_logger(__name__)


class BootstrapRunner:
    """Manages in-flight workspace bootstrap asyncio tasks.

    Parameters
    ----------
    state_store:
        DAO for the ``bootstrap_state`` table.
    connector_factory:
        Callable that receives ``(workspace_id, source, config)`` and returns
        a configured :class:`~metatron.core.interfaces.ConnectorInterface`.
    ingest_fn:
        Async callable injected into each :class:`~BootstrapJob` as the
        ingestion pipeline.
    settings:
        Application settings (for backoff parameters).
    """

    def __init__(
        self,
        *,
        state_store: BootstrapStateStore,
        connector_factory: Callable[[str, str, dict[str, Any]], ConnectorInterface],
        ingest_fn: Callable[..., Awaitable[None]],
        settings: Settings,
    ) -> None:
        self._store = state_store
        self._connector_factory = connector_factory
        self._ingest_fn = ingest_fn
        self._settings = settings
        # Maps workspace_id → (asyncio.Task, source, config)
        self._tasks: dict[str, tuple[asyncio.Task[None], str, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def schedule(
        self,
        workspace_id: str,
        *,
        source: str,
        config: dict[str, Any],
    ) -> bool:
        """Schedule a bootstrap job for *workspace_id*.

        Returns ``True`` if a new task was launched, ``False`` if one was
        already running (idempotent — caller can call safely on restart).
        """
        async with self._lock:
            existing = self._tasks.get(workspace_id)
            if existing is not None:
                task, _, _ = existing
                if not task.done():
                    logger.info(
                        "bootstrap.runner.already_running",
                        workspace_id=workspace_id,
                    )
                    return False
                # Task finished — remove the stale entry and re-schedule.
                del self._tasks[workspace_id]

            from metatron.workspaces.bootstrap.job import BootstrapJob

            connector = self._connector_factory(workspace_id, source, config)
            job = BootstrapJob(
                workspace_id,
                connector=connector,
                state_store=self._store,
                ingest_fn=self._ingest_fn,
                max_retries=self._settings.asoc_bootstrap_retry_max_attempts,
                backoff_base_seconds=self._settings.asoc_bootstrap_retry_backoff_base_seconds,
            )
            task = asyncio.create_task(job.run(), name=f"bootstrap-{workspace_id}")
            self._tasks[workspace_id] = (task, source, config)
            logger.info("bootstrap.runner.scheduled", workspace_id=workspace_id)
            return True

    async def cancel(self, workspace_id: str) -> bool:
        """Cancel in-flight bootstrap task.

        Returns True if a task was cancelled, False if none was running.
        Called by :meth:`WorkspaceManager.delete`.
        """
        async with self._lock:
            entry = self._tasks.pop(workspace_id, None)
            if entry is None:
                return False
            task, _, _ = entry
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            logger.info("bootstrap.runner.cancelled", workspace_id=workspace_id)
            return True

    async def reclaim_stale_bootstrapping(self, *, stale_after_seconds: int) -> int:
        """Reclaim crash-orphaned rows left in state=``bootstrapping``.

        Called once at lifespan startup.  Finds rows whose ``updated_at`` is
        older than *stale_after_seconds* and transitions them to ``failed`` so
        the retry cron picks them up.

        Returns the count of reclaimed rows.
        """
        threshold = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        stale_ids = await self._store.find_stale_bootstrapping(stale_threshold=threshold)
        count = 0
        for wid in stale_ids:
            with contextlib.suppress(Exception):
                await self._store.set_failed(
                    wid,
                    last_error="reclaimed at replica restart",
                    next_retry_at=datetime.now(UTC),
                    increment_retry=False,
                )
                count += 1
                logger.info("bootstrap.runner.reclaimed", workspace_id=wid)
        return count

    async def shutdown(self) -> None:
        """Cancel all in-flight tasks.  Called from lifespan shutdown."""
        async with self._lock:
            task_entries = list(self._tasks.values())
            self._tasks.clear()

        for task, _, _ in task_entries:
            if not task.done():
                task.cancel()
        for task, _, _ in task_entries:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        logger.info("bootstrap.runner.shutdown", cancelled=len(task_entries))

    def get_cached_source_config(
        self, workspace_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Return in-memory (source, config) for a workspace, or None if not cached."""
        entry = self._tasks.get(workspace_id)
        if entry is None:
            return None
        _, source, config = entry
        return source, config
