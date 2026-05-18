"""BootstrapRetryCron — periodic retry of failed workspace bootstraps (MTRNIX-352, T2).

One background task launched from the app lifespan.  On each tick it:

1. Queries ``bootstrap_state`` for failed rows whose ``next_retry_at <= NOW()``.
2. CAS-transitions each from ``failed`` → ``bootstrapping`` (so other replicas
   skip the same row).
3. Resolves (source, config) from the in-memory task cache or the connections
   table.
4. Calls :meth:`BootstrapRunner.schedule` to launch a new :class:`BootstrapJob`.

Loop runs forever until cancelled.  Consecutive PG errors trigger exponential
backoff (base 2 s, cap 60 s) before sleeping *interval_seconds*.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from metatron.workspaces.bootstrap.models import BootstrapStateEnum

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from metatron.workspaces.bootstrap.runner import BootstrapRunner
    from metatron.workspaces.bootstrap.store import BootstrapStateStore

logger = structlog.get_logger(__name__)

_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 60.0


class BootstrapRetryCron:
    """Periodic retry loop for failed bootstrap jobs.

    Parameters
    ----------
    state_store:
        DAO for the ``bootstrap_state`` table.
    runner:
        The singleton :class:`BootstrapRunner` used to re-schedule jobs.
    config_resolver:
        Async callable ``(workspace_id) -> (source, config)`` used to look up
        connection details for a workspace on retry.  For T2 the runner's
        in-memory cache is consulted first; this resolver is a fallback for the
        case where the replica restarted between the initial bootstrap and the
        retry.

        If the resolver raises :exc:`NotImplementedError` the retry for that
        workspace is skipped with a WARNING log.
        # TODO(T7): wire config_resolver to the connections table once T7 lands.
    interval_seconds:
        Sleep time between successful ticks.
    max_attempts:
        Passed to :meth:`~BootstrapStateStore.list_failed_ready_for_retry` so
        rows that have already exhausted all retries are not re-queued.
    """

    def __init__(
        self,
        *,
        state_store: BootstrapStateStore,
        runner: BootstrapRunner,
        config_resolver: Callable[[str], Awaitable[tuple[str, dict[str, Any]]]],
        interval_seconds: int,
        max_attempts: int,
    ) -> None:
        self._store = state_store
        self._runner = runner
        self._config_resolver = config_resolver
        self._interval = interval_seconds
        self._max_attempts = max_attempts

    async def run_once(self) -> int:
        """Execute one retry tick.

        Returns the count of jobs successfully launched.
        """
        now = datetime.now(UTC)
        candidates = await self._store.list_failed_ready_for_retry(
            now=now, max_attempts=self._max_attempts
        )

        launched = 0
        for row in candidates:
            wid = row.workspace_id
            try:
                # CAS: failed → bootstrapping.  Skip if another replica grabbed it.
                won = await self._store.cas_set_state(
                    wid,
                    from_state=BootstrapStateEnum.FAILED,
                    to_state=BootstrapStateEnum.BOOTSTRAPPING,
                )
                if not won:
                    logger.info("bootstrap.cron.cas_lost", workspace_id=wid)
                    continue

                # Resolve (source, config) — in-memory cache first, then resolver.
                cached = self._runner.get_cached_source_config(wid)
                if cached is not None:
                    source, config = cached
                else:
                    source, config = await self._config_resolver(wid)

                await self._runner.schedule(wid, source=source, config=config)
                launched += 1
                logger.info(
                    "bootstrap.cron.retry_scheduled",
                    workspace_id=wid,
                    retry_count=row.retry_count,
                )
            except NotImplementedError:
                logger.warning(
                    "bootstrap.cron.config_resolver_not_implemented",
                    workspace_id=wid,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "bootstrap.cron.retry_error",
                    workspace_id=wid,
                    exc_info=True,
                )

        return launched

    async def run_forever(self) -> None:
        """Run :meth:`run_once` in a bounded-error loop until cancelled.

        Consecutive PG errors trigger exponential backoff before retrying.
        """
        consecutive_errors = 0
        backoff = _BACKOFF_BASE

        while True:
            try:
                await self.run_once()
                consecutive_errors = 0
                backoff = _BACKOFF_BASE
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                consecutive_errors += 1
                logger.warning(
                    "bootstrap.cron.tick_error",
                    consecutive_errors=consecutive_errors,
                    next_backoff_seconds=backoff,
                    exc_info=True,
                )
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_CAP)
                continue

            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(self._interval)
