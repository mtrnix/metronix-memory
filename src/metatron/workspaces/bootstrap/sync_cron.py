"""asoc_sync_cron — periodic delta sync for ASOC ready workspaces (MTRNIX-357, T7).

Polls ``bootstrap_state`` for ``state='ready'`` workspaces every
``METATRON_ASOC_SYNC_INTERVAL_SECONDS`` (default 900 s = 15 min), then for each
workspace calls :meth:`AsocConnector.fetch` with ``since=last_synced_at`` and
ingests delta documents through the standard pipeline.  Updates
``last_synced_at`` on success.

Bounded concurrency via :attr:`Settings.asoc_sync_max_concurrent_workspaces`
(default 3).  Archived workspaces are excluded by the ``state='ready'`` filter.
Per-workspace failures do NOT abort the cron — they are logged and the loop
continues.

The cron mirrors :class:`~metatron.workspaces.bootstrap.cron.BootstrapRetryCron`
(``retry_cron.py``) in structure and backoff behaviour.

Architecture: launched as an ``asyncio.create_task`` in the app lifespan,
exactly like :class:`BootstrapRetryCron`.  Multi-replica safety is deferred to
Phase 2; MVP is single-replica and idempotent via content-hash dedup in the
ingestion pipeline.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from metatron.workspaces.bootstrap.models import BootstrapState
    from metatron.workspaces.bootstrap.store import BootstrapStateStore

logger = structlog.get_logger(__name__)

_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 60.0


class AsocSyncCron:
    """Bounded-error periodic delta-sync loop for ASOC ready workspaces.

    Parameters
    ----------
    state_store:
        DAO for the ``bootstrap_state`` table.
    connector_factory:
        Async callable ``(workspace_id) -> AsocConnector`` that resolves and
        configures a fresh :class:`~metatron.connectors.asoc.AsocConnector`
        for the given workspace.  Called once per workspace per tick.
    ingest_fn:
        Async callable ``(documents, workspace_id) -> None`` that passes delta
        documents through the standard ingestion pipeline.
    interval_seconds:
        Sleep time between successful ticks (default 900 = 15 min).
    max_concurrent_workspaces:
        Semaphore bound on parallel per-workspace syncs (default 3).
    """

    def __init__(
        self,
        *,
        state_store: BootstrapStateStore,
        connector_factory: Callable[[str], Awaitable[object]],
        ingest_fn: Callable[..., Awaitable[None]],
        interval_seconds: int,
        max_concurrent_workspaces: int,
    ) -> None:
        self._state_store = state_store
        self._connector_factory = connector_factory
        self._ingest_fn = ingest_fn
        self._interval_seconds = interval_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_workspaces)
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the loop to exit after the current tick completes."""
        self._stop_event.set()

    async def run_once(self) -> dict[str, int]:
        """Execute one delta-sync tick over all ready workspaces.

        Returns a stats dict with keys ``workspaces``, ``succeeded``, ``failed``.
        """
        try:
            workspaces = await self._state_store.list_ready_workspaces()
        except Exception:
            logger.exception("asoc.sync_cron.list_failed")
            return {"workspaces": 0, "succeeded": 0, "failed": 0}

        if not workspaces:
            logger.info("asoc.sync_cron.tick_empty")
            return {"workspaces": 0, "succeeded": 0, "failed": 0}

        tasks = [asyncio.create_task(self._sync_one(ws)) for ws in workspaces]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        succeeded = sum(1 for r in results if r is True)
        failed = sum(1 for r in results if r is not True)
        logger.info(
            "asoc.sync_cron.tick_complete",
            workspaces=len(workspaces),
            succeeded=succeeded,
            failed=failed,
        )
        return {"workspaces": len(workspaces), "succeeded": succeeded, "failed": failed}

    async def run_forever(self) -> None:
        """Run :meth:`run_once` in a bounded-error loop until :meth:`stop` is called.

        Consecutive tick-level errors trigger exponential backoff (base 2 s, cap 60 s)
        before the next attempt.  :exc:`asyncio.CancelledError` propagates immediately.
        """
        consecutive_errors = 0
        backoff = _BACKOFF_BASE

        while not self._stop_event.is_set():
            try:
                await self.run_once()
                consecutive_errors = 0
                backoff = _BACKOFF_BASE
            except asyncio.CancelledError:
                raise
            except Exception:
                consecutive_errors += 1
                logger.warning(
                    "asoc.sync_cron.tick_error",
                    consecutive_errors=consecutive_errors,
                    next_backoff_seconds=backoff,
                    exc_info=True,
                )
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_CAP)
                continue

            # Sleep until next tick or until stop() is called.
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_seconds,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _sync_one(self, ws_state: BootstrapState) -> bool:
        """Sync a single workspace under the semaphore.

        Per-workspace errors are caught and logged; the cron continues with
        remaining workspaces.  Returns ``True`` on success, ``False`` on failure.
        """
        async with self._semaphore:
            workspace_id = ws_state.workspace_id
            try:
                connector = await self._connector_factory(workspace_id)

                # Build fetch kwargs — pass resume hints from the last bootstrap
                # checkpoint when present (matches pattern in BootstrapJob, T4).
                fetch_kwargs: dict[str, object] = {"since": ws_state.last_synced_at}
                if ws_state.last_processed_resource:
                    fetch_kwargs["after_resource"] = ws_state.last_processed_resource
                if ws_state.last_processed_id:
                    fetch_kwargs["after_id"] = ws_state.last_processed_id

                documents = await connector.fetch(workspace_id, **fetch_kwargs)  # type: ignore[union-attr]
                if documents:
                    await self._ingest_fn(documents, workspace_id)

                await self._state_store.touch_last_synced_at(workspace_id, datetime.now(UTC))
                logger.info(
                    "asoc.sync_cron.workspace_synced",
                    workspace_id=workspace_id,
                    delta_count=len(documents) if documents else 0,
                )
                return True
            except Exception:
                logger.exception(
                    "asoc.sync_cron.workspace_failed",
                    workspace_id=workspace_id,
                )
                return False
