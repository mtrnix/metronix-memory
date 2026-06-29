"""Scheduled-scan safety net for the freshness pipeline (MTRNIX-316).

The primary freshness path is *write-triggered*: memory saves / KB syncs
call a producer that enqueues a ``FreshnessJob`` on the workspace queue.
Records that never receive a write (low-traffic workspaces, producer bugs,
forgotten imports) would otherwise age out of the freshness window and
never get demoted to ``STALE``. The scheduled-scan module closes that gap
by periodically asking each ``FreshnessTarget`` for its stale candidates
and enqueueing synthetic ``scheduled_scan`` jobs for them.

Scope in MTRNIX-316: memory only. KB target's ``list_stale_candidates``
returns an empty list by default (defer to MTRNIX-316 follow-up). The
orchestrator is target-agnostic so the KB opt-in is a one-line change in
the worker wiring.

Pipeline idempotence: enqueuing a record that was recently processed is
safe — the pipeline's ``freshness_job_received`` MachineEvent dedup-trail
catches the duplicate and the stage locks prevent concurrent work. At
worst the scan adds one extra ``freshness_job_processed`` row per
recently-scanned record.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from metronix.core.config import get_settings
from metronix.core.models import FreshnessJob
from metronix.freshness import metrics

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from metronix.freshness.coordination import CoordinationStore
    from metronix.freshness.targets import FreshnessTarget
    from metronix.storage.memory_postgres import MemoryPostgresStore

logger = structlog.get_logger()


@dataclass
class ScheduledScan:
    """One scheduled-scan orchestrator per target kind.

    The worker owns zero-or-more ``ScheduledScan`` instances (typically
    one for memory, one for KB). Each iteration of the worker's scan
    timer calls ``run()`` on every instance — failure in one target does
    not block the others because ``run()`` swallows its own errors.
    """

    target_kind: str
    target: FreshnessTarget
    coordination: CoordinationStore
    workspace_lister: Callable[[], Awaitable[list[str]]]
    stale_after_days: int
    batch_limit: int

    async def run(self) -> int:
        """Enqueue stale candidates for every workspace. Returns total enqueued.

        All failures are swallowed so a misbehaving workspace cannot take
        down the whole scan pass. Per-workspace errors bump the
        ``freshness_scheduled_scan_errors_total`` counter; the overall
        ``list_workspaces`` failure does the same. PG remains the source
        of truth; the next scan cycle will retry.
        """
        settings = get_settings()
        env_label = settings.env or ""
        older_than = datetime.now(UTC) - timedelta(days=self.stale_after_days)
        total = 0
        logger.info(
            "freshness.scheduled_scan.start",
            target_kind=self.target_kind,
            stale_after_days=self.stale_after_days,
            batch_limit=self.batch_limit,
        )
        try:
            workspaces = await self.workspace_lister()
        except Exception:
            logger.warning(
                "freshness.scheduled_scan.list_workspaces_failed",
                target_kind=self.target_kind,
                exc_info=True,
            )
            _inc_labeled(
                metrics.scheduled_scan_errors,
                env=env_label,
                target_kind=self.target_kind,
            )
            return 0

        for ws in workspaces:
            try:
                ids = await self.target.list_stale_candidates(
                    ws, older_than=older_than, limit=self.batch_limit
                )
                for rid in ids:
                    await self.coordination.enqueue_job(
                        FreshnessJob(
                            workspace_id=ws,
                            event_type="scheduled_scan",
                            target_kind=self.target_kind,
                            target_id=rid,
                            payload={"older_than_iso": older_than.isoformat()},
                        )
                    )
                if ids:
                    _inc_labeled(
                        metrics.scheduled_scan_jobs_enqueued,
                        env=env_label,
                        target_kind=self.target_kind,
                        amount=len(ids),
                    )
                    total += len(ids)
                    logger.info(
                        "freshness.scheduled_scan.enqueued",
                        workspace_id=ws,
                        target_kind=self.target_kind,
                        count=len(ids),
                    )
            except Exception:
                logger.warning(
                    "freshness.scheduled_scan.failed",
                    workspace_id=ws,
                    target_kind=self.target_kind,
                    exc_info=True,
                )
                _inc_labeled(
                    metrics.scheduled_scan_errors,
                    env=env_label,
                    target_kind=self.target_kind,
                )
        return total


def _inc_labeled(metric: object, *, env: str, target_kind: str, amount: int = 1) -> None:
    """Best-effort ``labels(...).inc(...)`` so a metrics failure cannot bite.

    Mirrors the MTRNIX-322 swallow pattern — a broken Prometheus registry
    must not disable the scheduled scan.
    """
    with contextlib.suppress(Exception):
        metric.labels(env=env, target_kind=target_kind).inc(amount)  # type: ignore[attr-defined]


def _inc_session_gc(metric: object, *, env: str, amount: int = 1) -> None:
    """Best-effort metric increment for the session-GC pass.

    Both ``memory_session_gc_deleted`` and ``memory_session_gc_errors`` carry
    only the ``env`` label — ``workspace_id`` was dropped to avoid unbounded
    cardinality in multi-tenant deployments.  Per-workspace data is available
    via structlog events (``memory.session.gc.workspace_deleted`` /
    ``memory.session.gc.workspace_failed``).
    """
    with contextlib.suppress(Exception):
        metric.labels(env=env).inc(amount)  # type: ignore[attr-defined]


@dataclass
class SessionGCPass:
    """Garbage-collect expired session memory rows (phase-2 memory-scopes).

    Sits in the freshness scheduled-scan loop because that is the only
    cross-workspace periodic timer we already operate. The actual work is
    a plain DELETE — NOT a lifecycle transition — so it deliberately does
    NOT go through Linker/Reconciler/Monitor/Curator. See D-P2-05.

    Gated by ``freshness_scheduled_scan_enabled``: if the flag is off the
    pass is never constructed (worker bootstrap skips it). Operators who
    disable the freshness pipeline accept that PG accumulates expired session
    rows until the flag is re-enabled.
    """

    pg_store: MemoryPostgresStore
    workspace_lister: Callable[[], Awaitable[list[str]]]
    grace_hours: int
    batch_limit: int = field(default=1000)

    async def run(self) -> int:
        """Delete expired session records past the grace window. Returns total deleted.

        All per-workspace failures are swallowed so a misbehaving workspace
        cannot take down the whole pass. The ``memory_session_gc_errors`` counter
        is bumped on each swallowed error.
        """
        settings = get_settings()
        env_label = settings.env or ""
        cutoff = datetime.now(UTC) - timedelta(hours=self.grace_hours)
        total = 0
        logger.info(
            "freshness.session_gc.start",
            grace_hours=self.grace_hours,
            cutoff=cutoff.isoformat(),
        )
        try:
            workspaces = await self.workspace_lister()
        except Exception:
            logger.warning("freshness.session_gc.list_workspaces_failed", exc_info=True)
            _inc_session_gc(metrics.memory_session_gc_errors, env=env_label)
            return 0

        for ws in workspaces:
            try:
                count = await self.pg_store.delete_session_records_past_grace(
                    ws,
                    grace_cutoff=cutoff,
                    limit=self.batch_limit,
                )
                if count:
                    _inc_session_gc(
                        metrics.memory_session_gc_deleted,
                        env=env_label,
                        amount=count,
                    )
                total += count
            except Exception:
                logger.warning(
                    "freshness.session_gc.workspace_failed",
                    workspace_id=ws,
                    exc_info=True,
                )
                _inc_session_gc(metrics.memory_session_gc_errors, env=env_label)

        logger.info("freshness.session_gc.completed", total_deleted=total)
        return total


__all__ = ["ScheduledScan", "SessionGCPass"]
