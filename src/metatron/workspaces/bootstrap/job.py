"""BootstrapJob — orchestrates fetch → ingest → checkpoint for one workspace (MTRNIX-352, T2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from metatron.workspaces.bootstrap.models import BootstrapStateEnum

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from metatron.core.interfaces import ConnectorInterface
    from metatron.workspaces.bootstrap.store import BootstrapStateStore

logger = structlog.get_logger(__name__)

# Sentinel value for an unknown total — connector may not know upfront.
_UNKNOWN_TOTAL: int | None = None


class BootstrapJob:
    """Fetch documents from a connector, ingest them, and track progress.

    This is a *fire-and-forget* background task — :meth:`run` does NOT raise.
    All errors are caught, stored as ``last_error`` in the DB, and the row is
    transitioned to ``failed`` for the retry cron to pick up.

    Parameters
    ----------
    workspace_id:
        ASOC workspace to bootstrap.
    connector:
        Data-source connector (T1 will supply ``AsocConnector``; T2 tests use a fake).
    state_store:
        DAO for the ``bootstrap_state`` table.
    ingest_fn:
        Async callable with the same signature as
        :func:`metatron.ingestion.pipeline.ingest_documents`.  Injected so
        tests can replace the full ingestion pipeline without DB/Qdrant setup.
    max_retries:
        Ceiling on :attr:`BootstrapState.retry_count` before giving up.
    backoff_base_seconds:
        Base for exponential backoff: ``delay = base * 2^(count-1)``.
    backoff_cap_seconds:
        Hard cap on backoff delay (default 1 hour).
    """

    def __init__(
        self,
        workspace_id: str,
        *,
        connector: ConnectorInterface,
        state_store: BootstrapStateStore,
        ingest_fn: Callable[..., Awaitable[None]],
        max_retries: int,
        backoff_base_seconds: float,
        backoff_cap_seconds: float = 3600.0,
    ) -> None:
        self.workspace_id = workspace_id
        self._connector = connector
        self._store = state_store
        self._ingest_fn = ingest_fn
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_cap_seconds = backoff_cap_seconds

    async def run(self) -> None:
        """Execute the bootstrap.  Never raises — all errors are stored in the DB."""
        logger.info("bootstrap.job.started", workspace_id=self.workspace_id)
        try:
            await self._do_run()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "bootstrap.job.fatal_error",
                workspace_id=self.workspace_id,
                error=str(exc),
            )
            # We already handled the error inside _do_run; this branch only fires if
            # the error-handling itself raised (e.g. DB down during set_failed).
            # Log and leave — state may still be 'bootstrapping'; reclaim will fix it.

    async def _do_run(self) -> None:
        # Read current state to support resume-from-checkpoint.
        state = await self._store.get(self.workspace_id)
        if state is None:
            logger.warning("bootstrap.job.no_state_row", workspace_id=self.workspace_id)
            return

        try:
            await self._store.update_checkpoint(self.workspace_id, current_step="fetch_start")

            # Resume from last checkpoint when supported by the concrete connector.
            # AsocConnector.fetch accepts after_resource / after_id as keyword-only
            # resume hints; other connectors use the base signature only.
            from metatron.connectors.asoc import AsocConnector

            if isinstance(self._connector, AsocConnector):
                documents = await self._connector.fetch(
                    self.workspace_id,
                    since=None,
                    after_resource=state.last_processed_resource,
                    after_id=state.last_processed_id,
                )
            else:
                documents = await self._connector.fetch(self.workspace_id, since=None)

            total = len(documents)
            await self._store.update_checkpoint(
                self.workspace_id,
                current_step="ingesting",
                total_count=total,
                progress=0.0,
            )

            # Ingest in one shot for MVP; T7 will split into resumable batches.
            await self._ingest_fn(
                documents,
                self.workspace_id,
            )

            await self._store.update_checkpoint(
                self.workspace_id,
                current_step="done",
                indexed_count=total,
                progress=1.0,
                last_processed_resource=None,
                last_processed_id=None,
            )

            await self._store.set_state(
                self.workspace_id,
                state=BootstrapStateEnum.READY,
                clear_error=True,
            )
            logger.info(
                "bootstrap.job.completed",
                workspace_id=self.workspace_id,
                indexed_count=total,
            )

        except Exception as exc:  # noqa: BLE001
            # Read current retry_count so we can compute the next delay correctly.
            current = await self._store.get(self.workspace_id)
            # retry_count here is BEFORE the increment that set_failed will apply.
            retry_count_before = current.retry_count if current else 0
            # After set_failed increments, the new count = retry_count_before + 1.
            next_retry = self._compute_next_retry(retry_count_before + 1)
            logger.warning(
                "bootstrap.job.failed",
                workspace_id=self.workspace_id,
                error=str(exc),
                next_retry_at=next_retry,
            )
            await self._store.set_failed(
                self.workspace_id,
                last_error=str(exc),
                next_retry_at=next_retry,
                increment_retry=True,
            )

    def _compute_next_retry(self, retry_count: int) -> datetime | None:
        """Compute the datetime for the next retry attempt.

        *retry_count* is the value **after** the increment in
        :meth:`~BootstrapStateStore.set_failed` (i.e. the total number of
        attempts including the one that just failed).

        Returns ``None`` when ``retry_count >= max_retries`` (give up).

        Backoff formula::

            delay = min(base * 2^(retry_count - 1), cap)

        Examples (base=60, cap=3600)::

            retry_count=1  →  60 s
            retry_count=2  →  120 s
            retry_count=3  →  240 s
            retry_count=5  →  960 s
            retry_count=7  →  3600 s (capped)
        """
        if retry_count >= self.max_retries:
            return None
        delay = min(
            self.backoff_base_seconds * (2 ** (retry_count - 1)),
            self.backoff_cap_seconds,
        )
        return datetime.now(UTC) + timedelta(seconds=delay)
