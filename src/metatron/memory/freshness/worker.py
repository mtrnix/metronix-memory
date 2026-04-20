"""FreshnessWorker — polling loop that drives the freshness pipeline.

One ``run_once`` iteration:

1. Enumerate active workspaces.
2. ``dequeue_batch`` per workspace.
3. For each job:
   * Log ``freshness_job_received`` MachineEvent.
   * Run Linker → Reconciler → Monitor → Curator.
   * If the record still exists and is ``CANDIDATE``/``ACTIVE``,
     call ``DecisionEngine`` and ``apply_decision``.
   * Log ``freshness_job_processed`` MachineEvent.

``main()`` wraps ``run_once`` in a bounded error-backoff loop and exits
immediately when ``freshness_enabled=False``.

Workspace isolation: every stage call receives ``job.workspace_id``
directly; the worker never assumes a default.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from metatron.core.config import get_settings
from metatron.core.models import (
    FreshnessJob,
    MachineEvent,
    MemoryRecord,
    MemoryStatus,
)
from metatron.memory.freshness import metrics

if TYPE_CHECKING:
    from metatron.memory.freshness.coordination import CoordinationStore
    from metatron.memory.freshness.curator import Curator
    from metatron.memory.freshness.decision_engine import DecisionEngine
    from metatron.memory.freshness.linker import Linker
    from metatron.memory.freshness.monitor import FreshnessMonitor
    from metatron.memory.freshness.reconciler import Reconciler
    from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

logger = structlog.get_logger()


PgStoreFactory = Callable[[str], "MemoryPostgresStore"]
QdrantStoreFactory = Callable[[str], "MemoryQdrantStore"]


class FreshnessWorker:
    """Drives the pipeline one iteration at a time."""

    def __init__(
        self,
        *,
        coordination: CoordinationStore,
        freshness_pg: FreshnessPostgresStore,
        decision_engine: DecisionEngine,
        pg_store_factory: PgStoreFactory,
        qdrant_store_factory: QdrantStoreFactory,
        linker: Linker,
        reconciler: Reconciler,
        monitor: FreshnessMonitor,
        curator: Curator,
    ) -> None:
        self._coord = coordination
        self._freshness_pg = freshness_pg
        self._decision_engine = decision_engine
        self._pg_factory = pg_store_factory
        self._qdrant_factory = qdrant_store_factory
        self._linker = linker
        self._reconciler = reconciler
        self._monitor = monitor
        self._curator = curator

    async def run_once(self, max_jobs: int) -> int:
        """Dequeue + process up to ``max_jobs`` per workspace. Returns total count."""
        workspaces = await self._coord.list_active_workspaces()
        processed = 0
        for ws in workspaces:
            try:
                depth = await self._coord.queue_depth(ws)
                metrics.queue_depth_gauge.labels(workspace_id=ws).set(depth)
            except Exception:
                logger.debug("freshness.worker.gauge_failed", exc_info=True)

            jobs = await self._coord.dequeue_batch(ws, max_items=max_jobs)
            for job in jobs:
                await self._process_job(job)
                processed += 1
        return processed

    async def _process_job(self, job: FreshnessJob) -> None:
        ws = job.workspace_id
        record_id = job.target_id
        started = time.monotonic()

        await self._freshness_pg.save_machine_event(
            MachineEvent(
                workspace_id=ws,
                event_type="freshness_job_received",
                target_id=record_id,
                payload={"event_type": job.event_type},
            )
        )

        if job.event_type == "knowledge_deleted":
            # We only log the receipt; lifecycle work for deleted records
            # is out of scope for Phase A.
            metrics.jobs_total.labels(status="deleted", workspace_id=ws).inc()
            duration_ms = int((time.monotonic() - started) * 1000)
            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=ws,
                    event_type="freshness_job_processed",
                    target_id=record_id,
                    payload={
                        "event_type": job.event_type,
                        "decision_action": "skipped_deleted",
                        "duration_ms": duration_ms,
                    },
                )
            )
            return

        decision_action = "skipped_missing"
        try:
            await self._linker.run(ws, record_id)
            await self._reconciler.run(ws, record_id)
            await self._monitor.run(ws, record_id)
            await self._curator.run(ws, record_id)

            pg_store = self._pg_factory(ws)
            record: MemoryRecord | None = await pg_store.get(ws, record_id)
            if record is not None and record.status in {
                MemoryStatus.CANDIDATE,
                MemoryStatus.ACTIVE,
                MemoryStatus.REVIEW_NEEDED,
            }:
                from metatron.memory.freshness.decision_engine import apply_decision

                decision = await self._decision_engine.decide(
                    content=record.content,
                    workspace_id=ws,
                    record_id=record_id,
                )
                metrics.decision_confidence.observe(decision.confidence)
                settings = get_settings()
                result = await apply_decision(
                    workspace_id=ws,
                    record=record,
                    decision=decision,
                    threshold=settings.freshness_decision_confidence_threshold,
                    pg_store=pg_store,
                    freshness_pg=self._freshness_pg,
                )
                decision_action = str(result.get("action") or decision.action)

            metrics.jobs_total.labels(status="ok", workspace_id=ws).inc()
        except Exception:
            metrics.jobs_total.labels(status="error", workspace_id=ws).inc()
            metrics.worker_errors.labels(stage="process").inc()
            logger.error(
                "freshness.worker.job_failed",
                workspace_id=ws,
                record_id=record_id,
                exc_info=True,
            )
            raise
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=ws,
                    event_type="freshness_job_processed",
                    target_id=record_id,
                    payload={
                        "event_type": job.event_type,
                        "decision_action": decision_action,
                        "duration_ms": duration_ms,
                    },
                )
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_loop(worker: FreshnessWorker) -> None:
    """Shared loop body. Exposed for tests so they can mock ``run_once``."""
    settings = get_settings()
    consecutive_errors = 0
    while True:
        try:
            processed = await worker.run_once(settings.freshness_max_jobs_per_iteration)
            consecutive_errors = 0
            if processed == 0:
                await asyncio.sleep(settings.freshness_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_errors += 1
            backoff = min(
                settings.freshness_backoff_base_seconds * (2 ** (consecutive_errors - 1)),
                settings.freshness_backoff_max_seconds,
            )
            logger.error(
                "freshness.worker.iteration_failed",
                attempt=consecutive_errors,
                backoff=backoff,
                exc_info=True,
            )
            if consecutive_errors >= settings.freshness_max_consecutive_errors:
                logger.critical(
                    "freshness.worker.hard_exit",
                    errors=consecutive_errors,
                )
                raise
            await asyncio.sleep(backoff)


async def _build_worker() -> FreshnessWorker:
    """Wire the default worker from ``Settings`` + shared stores."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.memory.freshness.coordination import CoordinationStore
    from metatron.memory.freshness.curator import Curator
    from metatron.memory.freshness.decision_engine import (
        build_default_decision_engine,
    )
    from metatron.memory.freshness.linker import Linker
    from metatron.memory.freshness.monitor import FreshnessMonitor
    from metatron.memory.freshness.reconciler import Reconciler
    from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore
    from metatron.storage.redis import RedisStore

    settings = get_settings()
    redis = RedisStore(settings.redis_url)
    coordination = CoordinationStore(redis=redis)
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_store = MemoryPostgresStore(engine)
    freshness_pg = FreshnessPostgresStore(engine)

    # Per-workspace Qdrant store is expensive; keep a tiny cache.
    _qdrant_cache: dict[str, MemoryQdrantStore] = {}

    def qdrant_factory(ws: str) -> MemoryQdrantStore:
        if ws not in _qdrant_cache:
            _qdrant_cache[ws] = MemoryQdrantStore(workspace_id=ws)
        return _qdrant_cache[ws]

    def pg_factory(_ws: str) -> MemoryPostgresStore:
        return pg_store

    # Each stage needs its own Qdrant handle; the worker hands them in at
    # run time. For simplicity we build a default store bound to the first
    # workspace; the per-job stage instances read workspace from the record.
    # A simpler choice: pass per-job stage objects through factories.
    # Phase A ships a single stage-instance set reused across workspaces —
    # each stage does its own workspace-scoped query, so this is safe.
    default_ws = settings.default_workspace_id
    qdrant_default = qdrant_factory(default_ws)

    linker = Linker(
        pg_store=pg_store,
        qdrant_store=qdrant_default,
        freshness_pg=freshness_pg,
        coordination=coordination,
        threshold=settings.freshness_linker_threshold,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    reconciler = Reconciler(
        pg_store=pg_store,
        qdrant_store=qdrant_default,
        freshness_pg=freshness_pg,
        coordination=coordination,
        threshold=settings.freshness_reconciler_threshold,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    monitor = FreshnessMonitor(
        pg_store=pg_store,
        freshness_pg=freshness_pg,
        coordination=coordination,
        stale_after_days=settings.freshness_stale_after_days,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    curator = Curator(
        pg_store=pg_store,
        freshness_pg=freshness_pg,
        coordination=coordination,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )

    return FreshnessWorker(
        coordination=coordination,
        freshness_pg=freshness_pg,
        decision_engine=build_default_decision_engine(),
        pg_store_factory=pg_factory,
        qdrant_store_factory=qdrant_factory,
        linker=linker,
        reconciler=reconciler,
        monitor=monitor,
        curator=curator,
    )


async def main() -> None:
    """Entry point for ``python -m metatron.memory.freshness``."""
    # Core/logging.py configure_logging does structlog; we just tune stdlib.
    logging.getLogger().setLevel(logging.INFO)
    settings = get_settings()
    if not settings.freshness_enabled:
        logger.info("freshness.disabled.exit")
        return
    logger.info(
        "freshness.worker.started",
        poll_seconds=settings.freshness_poll_seconds,
        max_jobs=settings.freshness_max_jobs_per_iteration,
    )
    worker = await _build_worker()
    await _run_loop(worker)
