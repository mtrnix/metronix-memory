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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob
from metatron.freshness import metrics

if TYPE_CHECKING:
    from metatron.freshness.coordination import CoordinationStore
    from metatron.freshness.targets import FreshnessTarget

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
    try:
        metric.labels(env=env, target_kind=target_kind).inc(amount)  # type: ignore[attr-defined]
    except Exception:
        pass


__all__ = ["ScheduledScan"]
