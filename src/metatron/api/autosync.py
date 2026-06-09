"""In-process autosync scheduler (MTRNIX-396).

Runs as an asyncio background task in the API process lifespan.
On each tick it queries for connections whose ``next_run_at`` is due,
claims them atomically, and spawns ``_run_connection_sync`` as a
managed asyncio.Task.

See ``docs/adr/2026-06-09-autosync-architecture.md`` for the design
rationale (in-process vs. separate worker, autosync-on-by-default).

Layer: L6 — API. Imports from L3/L2/L1 only.
"""

from __future__ import annotations

import asyncio
import uuid
import zoneinfo
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from croniter import croniter  # type: ignore[import-untyped]

from metatron.connectors.schemas import CONNECTOR_SCHEMAS

if TYPE_CHECKING:
    from metatron.core.config import Settings
    from metatron.core.events import EventBus
    from metatron.storage.postgres import PostgresStore

logger = structlog.get_logger(__name__)


class AutosyncScheduler:
    """Poll for due connections and spawn incremental syncs.

    Designed to be constructed once in ``lifespan()`` and run as a
    long-lived ``asyncio.Task``.  All heavy sync work is delegated to
    ``_run_connection_sync`` from ``api.routes.connections``; this class
    is purely the scheduling/claiming shell.

    Thread-safety: all public methods are called from the same asyncio
    event loop thread — no locking needed.
    """

    def __init__(
        self,
        store: PostgresStore,
        settings: Settings,
        event_bus: EventBus | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._event_bus = event_bus
        self._inflight: set[asyncio.Task[None]] = set()

        # Resolve timezone — fall back to UTC on bad config and warn once.
        try:
            self._tz = zoneinfo.ZoneInfo(settings.autosync_timezone)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            logger.warning(
                "autosync.bad_timezone",
                timezone=settings.autosync_timezone,
                fallback="UTC",
            )
            self._tz = zoneinfo.ZoneInfo("UTC")

    async def run_forever(self) -> None:
        """Main scheduler loop.  Run as an asyncio.Task by lifespan().

        Sleeps ``autosync_poll_seconds`` between ticks.  A failing tick
        is logged and skipped — a single bad tick must never kill the loop.
        ``asyncio.CancelledError`` is re-raised immediately (clean shutdown).
        """
        logger.info(
            "autosync.loop.started",
            poll_seconds=self._settings.autosync_poll_seconds,
            timezone=self._settings.autosync_timezone,
            max_concurrent=self._settings.autosync_max_concurrent,
        )
        while True:
            try:
                await asyncio.sleep(self._settings.autosync_poll_seconds)
                await self.tick()
            except asyncio.CancelledError:
                logger.info("autosync.loop.cancelled")
                raise
            except Exception:
                logger.warning("autosync.tick.error", exc_info=True)

    async def tick(self) -> None:
        """Single scheduler tick: claim due connections and spawn syncs."""
        free = self._settings.autosync_max_concurrent - len(self._inflight)
        if free <= 0:
            logger.debug(
                "autosync.tick.at_capacity",
                inflight=len(self._inflight),
                max_concurrent=self._settings.autosync_max_concurrent,
            )
            return

        due = await self._store.list_due_autosync_connections(limit=free)
        if not due:
            return

        logger.debug("autosync.tick.due_found", count=len(due))

        for row in due:
            await self._process_due_row(row)

    async def _process_due_row(self, row: dict[str, Any]) -> None:
        """Try to claim and launch a sync for one due connection row."""
        connection_id: str = row["id"]
        connector_type: str = row["connector_type"]
        sync_cron: str = row["sync_cron"]
        workspace_id: str = row["workspace_id"]

        # Defensive: skip channels that somehow slipped past the DB filter.
        schema = CONNECTOR_SCHEMAS.get(connector_type)
        if schema is None or schema.category != "connector":
            logger.debug(
                "autosync.tick.skip_non_connector",
                connection_id=connection_id,
                connector_type=connector_type,
            )
            return

        # Compute next_run_at from the cron in the configured timezone.
        # We store UTC; croniter is initialized with now-in-tz so it
        # interprets the schedule in the user's timezone.
        now_in_tz = datetime.now(self._tz)
        try:
            cron = croniter(sync_cron, now_in_tz)
            next_local: datetime = cron.get_next(datetime)
        except Exception:
            logger.warning(
                "autosync.tick.bad_cron",
                connection_id=connection_id,
                sync_cron=sync_cron,
                exc_info=True,
            )
            return

        # Normalize to UTC for the timestamptz column.
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=self._tz)
        next_run_at = next_local.astimezone(UTC)

        # Atomic claim — only one replica wins.
        claimed = await self._store.claim_connection_for_autosync(connection_id, next_run_at)
        if not claimed:
            logger.debug(
                "autosync.tick.claim_lost",
                connection_id=connection_id,
            )
            return

        # Fetch decrypted config so we can pass it to the sync task.
        fernet_key = self._settings.fernet_key
        if not fernet_key:
            logger.warning(
                "autosync.tick.no_fernet_key",
                connection_id=connection_id,
            )
            # Release the claim — set back to active so the next tick retries.
            try:
                await self._store.update_connection_status(connection_id, status="active")
            except Exception:
                logger.warning(
                    "autosync.tick.claim_release_failed",
                    connection_id=connection_id,
                    exc_info=True,
                )
            return

        conn_dict = await self._store.get_connection_decrypted(connection_id, fernet_key)
        if conn_dict is None:
            logger.warning(
                "autosync.tick.connection_vanished",
                connection_id=connection_id,
            )
            return

        # Build sync_id mirroring trigger_sync's convention.
        sync_id = f"sync_{uuid.uuid4().hex[:12]}"

        # Parse last_synced_at cursor.
        last_synced_iso: str | None = conn_dict.get("last_synced_at")
        last_synced_dt: datetime | None = None
        if last_synced_iso:
            try:
                last_synced_dt = datetime.fromisoformat(last_synced_iso)
            except (ValueError, TypeError):
                logger.warning(
                    "autosync.cursor_parse_failed",
                    connection_id=connection_id,
                    raw=last_synced_iso,
                )

        # Pre-insert running sync_log row (same pattern as trigger_sync).
        try:
            await self._store.create_sync_log(
                sync_id=sync_id,
                workspace_id=workspace_id,
                connection_id=connection_id,
                connector_type=connector_type,
                trigger="scheduled",
            )
        except Exception:
            logger.warning(
                "autosync.sync_log.create_failed",
                sync_id=sync_id,
                connection_id=connection_id,
                exc_info=True,
            )
            # Non-fatal: sync still runs, just with no log row.

        # Import lazily to avoid a circular import at module load time.
        # Both _run_connection_sync and _get_registry live in api.routes.connections
        # (L6) — no layer violation.
        from metatron.api.routes.connections import _run_connection_sync

        task: asyncio.Task[None] = asyncio.create_task(
            _run_connection_sync(
                sync_id=sync_id,
                connection_id=connection_id,
                connector_type=connector_type,
                config=conn_dict["config"],
                workspace_id=workspace_id,
                store=self._store,
                event_bus=self._event_bus,
                force_full=False,
                last_synced_at=last_synced_dt,
            ),
            name=f"autosync-{connection_id[:8]}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

        logger.info(
            "autosync.sync.spawned",
            sync_id=sync_id,
            connection_id=connection_id,
            connector_type=connector_type,
            workspace_id=workspace_id,
            next_run_at=next_run_at.isoformat(),
        )
