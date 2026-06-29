"""FreshnessWorker — polling loop that drives the freshness pipeline.

One ``run_once`` iteration:

1. Tick the heartbeat key (MTRNIX-316) so live reclaimers know we're alive.
2. Every ``freshness_reclaim_interval_iterations`` iterations, run the
   reclaim pass over any dead peer's processing list.
3. If the scheduled-scan timer is due, kick off a safety-net scan per
   registered ``ScheduledScan`` instance.
4. Enumerate active workspaces.
5. ``dequeue_batch`` per workspace — items are LMOVE'd onto the per-worker
   processing list (``freshness:{env}:processing:{worker_id}``).
6. For each job:
   * Log ``freshness_job_received`` MachineEvent (with ``target_kind``).
   * Dispatch to the pipeline matching ``job.target_kind``.
   * Linker → Reconciler → Monitor → Curator.
   * If the record still exists and is eligible, call ``DecisionEngine``
     + ``apply_decision`` through the target adapter.
   * Log ``freshness_job_processed`` MachineEvent.
   * In the outer ``finally`` — call ``complete_job`` so the job is LREM'd
     from the processing list whether we succeeded or raised.

``main()`` builds the worker, runs a one-shot reclaim + optional legacy
drain, then enters the bounded error-backoff loop. On graceful shutdown
(asyncio.CancelledError) ``release_worker`` deletes the heartbeat key so
peers don't waste effort trying to reclaim a shutting-down worker.

Workspace isolation: every stage call receives ``job.workspace_id``
directly; the worker never assumes a default. Processing lists are
per-worker but each serialised job carries its own ``workspace_id`` —
reclaim routes items back to the correct queue.

Phase B (MTRNIX-313): the worker hosts two pipeline stacks (memory + KB)
and routes jobs on ``target_kind``. When the KB flag is off and no KB jobs
are ever enqueued, the memory path is byte-identical to Phase A.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

from metronix.core.config import get_settings
from metronix.core.models import FreshnessJob, LifecycleStatus, MachineEvent
from metronix.freshness import metrics
from metronix.freshness.worker_id import build_worker_id
from metronix.llm.telemetry import set_telemetry_context

if TYPE_CHECKING:
    from metronix.freshness.coordination import CoordinationStore
    from metronix.freshness.decision_engine import DecisionEngine
    from metronix.freshness.scheduled_scan import ScheduledScan, SessionGCPass
    from metronix.freshness.stages.curator import Curator
    from metronix.freshness.stages.linker import Linker
    from metronix.freshness.stages.monitor import FreshnessMonitor
    from metronix.freshness.stages.reconciler import Reconciler
    from metronix.freshness.targets import FreshnessTarget
    from metronix.storage.freshness_pg import FreshnessStore

logger = structlog.get_logger()


@dataclass
class _Pipeline:
    """Bundle of stage instances + adapter for one target kind."""

    linker: Linker
    reconciler: Reconciler
    monitor: FreshnessMonitor
    curator: Curator
    target: FreshnessTarget


class FreshnessWorker:
    """Drives the pipeline one iteration at a time.

    MTRNIX-316 adds:

    * ``worker_id`` — composed via :func:`build_worker_id` at bootstrap.
    * ``scheduled_scanners`` — zero-or-more :class:`ScheduledScan` instances.
    * Timing knobs: ``heartbeat_ttl``, ``reclaim_interval_iterations``,
      ``scheduled_scan_interval_seconds``. All default to the ``Settings``
      values when not supplied.

    Phase A constructor kwargs (``linker=``, ``reconciler=``, ...) are still
    accepted for backward compatibility with Phase A test fixtures; when
    supplied they are treated as an implicit ``memory_record`` pipeline.
    New code should pass ``pipelines=`` — a ``{target_kind: _Pipeline}``
    mapping.
    """

    def __init__(
        self,
        *,
        coordination: CoordinationStore,
        freshness_pg: FreshnessStore,
        decision_engine: DecisionEngine,
        pipelines: dict[str, _Pipeline] | None = None,
        # MTRNIX-316 reliability kwargs.
        worker_id: str | None = None,
        scheduled_scanners: list[ScheduledScan] | None = None,
        session_gc_passes: list[SessionGCPass] | None = None,
        heartbeat_ttl: int | None = None,
        reclaim_interval_iterations: int | None = None,
        scheduled_scan_interval_seconds: int | None = None,
        # Phase A compat kwargs (deprecated, prefer ``pipelines``).
        linker: Linker | None = None,
        reconciler: Reconciler | None = None,
        monitor: FreshnessMonitor | None = None,
        curator: Curator | None = None,
        target: FreshnessTarget | None = None,
    ) -> None:
        self._coord = coordination
        self._freshness_pg = freshness_pg
        self._decision_engine = decision_engine

        if pipelines is None:
            pipelines = {}
        if (
            linker is not None
            and reconciler is not None
            and monitor is not None
            and curator is not None
            and target is not None
        ):
            pipelines.setdefault(
                target.kind,
                _Pipeline(
                    linker=linker,
                    reconciler=reconciler,
                    monitor=monitor,
                    curator=curator,
                    target=target,
                ),
            )
        self._pipelines = pipelines

        settings = get_settings()
        self._worker_id = worker_id or build_worker_id()
        self._heartbeat_ttl = (
            heartbeat_ttl
            if heartbeat_ttl is not None
            else settings.freshness_heartbeat_ttl_seconds
        )
        self._reclaim_interval_iterations = (
            reclaim_interval_iterations
            if reclaim_interval_iterations is not None
            else settings.freshness_reclaim_interval_iterations
        )
        self._scheduled_scan_interval_seconds = (
            scheduled_scan_interval_seconds
            if scheduled_scan_interval_seconds is not None
            else settings.freshness_scheduled_scan_interval_seconds
        )
        self._scheduled_scanners: list[ScheduledScan] = list(scheduled_scanners or [])
        self._session_gc_passes: list[SessionGCPass] = list(session_gc_passes or [])

        self._iteration_count = 0
        # Start at 0.0 so the first tick fires immediately (the scan is
        # cheap — one PG enumerate + a bounded per-workspace SELECT — and
        # operators appreciate the "scan happened on startup" signal).
        self._last_scan_monotonic = 0.0

        logger.info(
            "freshness.worker.worker_id_assigned",
            worker_id=self._worker_id,
            heartbeat_ttl=self._heartbeat_ttl,
            reclaim_interval=self._reclaim_interval_iterations,
            scheduled_scan_interval=self._scheduled_scan_interval_seconds,
            scheduled_scanners=len(self._scheduled_scanners),
        )

    @property
    def worker_id(self) -> str:
        return self._worker_id

    async def run_once(self, max_jobs: int) -> int:
        """Dequeue + process up to ``max_jobs`` per workspace."""
        self._iteration_count += 1

        # 1. Heartbeat tick so peers know we're alive.
        await self._coord.tick_heartbeat(self._worker_id, self._heartbeat_ttl)

        # 2. Periodic reclaim pass.
        if self._iteration_count % max(self._reclaim_interval_iterations, 1) == 0:
            await self._reclaim_all_orphans()

        # 3. Scheduled scan (time-based).
        if self._scheduled_scanners and self._is_scan_due():
            await self._run_scheduled_scans()

        # 4. Regular dequeue + process loop.
        workspaces = await self._coord.list_active_workspaces()
        processed = 0
        for ws in workspaces:
            try:
                depth = await self._coord.queue_depth(ws)
                metrics.queue_depth_gauge.labels(workspace_id=ws).set(depth)
            except Exception:
                logger.debug("freshness.worker.gauge_failed", exc_info=True)

            jobs = await self._coord.dequeue_batch(
                ws, max_items=max_jobs, worker_id=self._worker_id
            )
            for job in jobs:
                await self._process_job(job)
                processed += 1
        return processed

    async def _reclaim_all_orphans(self) -> None:
        """Scan for dead-worker processing lists and drain each.

        All failures are swallowed so a flaky Redis cannot take down the
        main loop. Per-stage errors bump
        ``freshness_reclaim_errors_total``.
        """
        settings = get_settings()
        env_label = settings.env or ""
        try:
            worker_ids = await self._coord.list_processing_workers()
        except Exception:
            _inc_reclaim_error(env_label, "discover")
            logger.warning("freshness.reclaim.discover_failed", exc_info=True)
            return
        logger.info(
            "freshness.reclaim.start",
            worker_id=self._worker_id,
            worker_count=len(worker_ids),
        )
        for wid in worker_ids:
            if wid == self._worker_id:
                continue  # never reclaim self
            try:
                n = await self._coord.reclaim_worker_orphans(wid)
                if n:
                    logger.info(
                        "freshness.reclaim.jobs_recovered",
                        dead_worker_id=wid,
                        count=n,
                    )
            except Exception:
                _inc_reclaim_error(env_label, "drain")
                logger.warning(
                    "freshness.reclaim.drain_failed",
                    dead_worker_id=wid,
                    exc_info=True,
                )

    async def _run_scheduled_scans(self) -> None:
        """Run each registered ``ScheduledScan.run()`` and ``SessionGCPass.run()``; update timer.

        Both ``ScheduledScan.run`` and ``SessionGCPass.run`` swallow their own
        errors; we do not need an extra try/except here.
        """
        for scanner in self._scheduled_scanners:
            await scanner.run()
        for gc in self._session_gc_passes:
            await gc.run()
        self._last_scan_monotonic = time.monotonic()

    def _is_scan_due(self) -> bool:
        """Return True when the scheduled-scan timer has elapsed."""
        now = time.monotonic()
        elapsed = now - self._last_scan_monotonic
        return elapsed >= self._scheduled_scan_interval_seconds

    async def _process_job(self, job: FreshnessJob) -> None:
        ws = job.workspace_id
        target_id = job.target_id
        target_kind = job.target_kind or "memory_record"
        started = time.monotonic()

        # Integration-test knob (MTRNIX-316): widen the window between LMOVE
        # and LREM so the SIGKILL test can fire mid-batch deterministically.
        # No-op in production when the env var is unset.
        test_sleep_ms = os.environ.get("METRONIX_FRESHNESS_TEST_PROCESS_SLEEP_MS")
        if test_sleep_ms:
            with contextlib.suppress(ValueError):
                await asyncio.sleep(int(test_sleep_ms) / 1000)

        pipeline = self._pipelines.get(target_kind)
        if pipeline is None:
            logger.warning(
                "freshness.worker.unknown_target_kind",
                workspace_id=ws,
                target_kind=target_kind,
                target_id=target_id,
            )
            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=ws,
                    event_type="freshness_job_processed",
                    target_kind=target_kind,
                    target_id=target_id,
                    payload={
                        "event_type": job.event_type,
                        "decision_action": "skipped_unknown_target_kind",
                        "duration_ms": 0,
                    },
                )
            )
            # Still LREM the job from the processing list (outer finally).
            await self._coord.complete_job(self._worker_id, job)
            return

        await self._freshness_pg.save_machine_event(
            MachineEvent(
                workspace_id=ws,
                event_type="freshness_job_received",
                target_kind=target_kind,
                target_id=target_id,
                payload={"event_type": job.event_type},
            )
        )

        if job.event_type == "knowledge_deleted":
            metrics.jobs_total.labels(status="deleted", workspace_id=ws).inc()
            duration_ms = int((time.monotonic() - started) * 1000)
            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=ws,
                    event_type="freshness_job_processed",
                    target_kind=target_kind,
                    target_id=target_id,
                    payload={
                        "event_type": job.event_type,
                        "decision_action": "skipped_deleted",
                        "duration_ms": duration_ms,
                    },
                )
            )
            await self._coord.complete_job(self._worker_id, job)
            return

        decision_action = "skipped_missing"
        with set_telemetry_context(
            workspace_id=ws,
            source="freshness",
            correlation_id=uuid4(),
        ):
            try:
                await pipeline.linker.run(ws, target_id)
                await pipeline.reconciler.run(ws, target_id)
                await pipeline.monitor.run(ws, target_id)
                await pipeline.curator.run(ws, target_id)

                record = await pipeline.target.get(ws, target_id)
                eligible_statuses = {
                    LifecycleStatus.ACTIVE,
                    LifecycleStatus.REVIEW_NEEDED,
                }
                if pipeline.target.supports_candidate_promotion:
                    eligible_statuses.add(LifecycleStatus.CANDIDATE)
                if record is not None and record.status in eligible_statuses:
                    from metronix.freshness.apply_decision import apply_decision

                    decision = await self._decision_engine.decide(
                        content=record.content,
                        workspace_id=ws,
                        record_id=target_id,
                    )
                    metrics.decision_confidence.observe(decision.confidence)
                    settings = get_settings()
                    result = await apply_decision(
                        workspace_id=ws,
                        record=record,
                        decision=decision,
                        threshold=settings.freshness_decision_confidence_threshold,
                        target=pipeline.target,
                        freshness_store=self._freshness_pg,
                    )
                    decision_action = str(result.get("action") or decision.action)

                metrics.jobs_total.labels(status="ok", workspace_id=ws).inc()
            except Exception:
                metrics.jobs_total.labels(status="error", workspace_id=ws).inc()
                metrics.worker_errors.labels(stage="process").inc()
                logger.error(
                    "freshness.worker.job_failed",
                    workspace_id=ws,
                    target_kind=target_kind,
                    target_id=target_id,
                    exc_info=True,
                )
                raise
            finally:
                duration_ms = int((time.monotonic() - started) * 1000)
                await self._freshness_pg.save_machine_event(
                    MachineEvent(
                        workspace_id=ws,
                        event_type="freshness_job_processed",
                        target_kind=target_kind,
                        target_id=target_id,
                        payload={
                            "event_type": job.event_type,
                            "decision_action": decision_action,
                            "duration_ms": duration_ms,
                        },
                    )
                )
                # LREM the job from the processing list (MTRNIX-316). Must
                # happen whether we succeeded or raised so the orphan-reclaim
                # pass does not re-process a job we already completed.
                await self._coord.complete_job(self._worker_id, job)


def _inc_reclaim_error(env_label: str, stage: str) -> None:
    with contextlib.suppress(Exception):
        metrics.reclaim_errors.labels(env=env_label, stage=stage).inc()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run_loop(worker: FreshnessWorker) -> None:
    """Shared loop body. Exposed for tests so they can mock ``run_once``.

    MTRNIX-316: always calls ``release_worker`` on exit so a graceful
    shutdown proactively drops the heartbeat key (peers don't waste
    effort reclaiming a worker that's already gone).
    """
    settings = get_settings()
    consecutive_errors = 0
    try:
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
    finally:
        # Best-effort heartbeat cleanup. Do NOT await inside the
        # CancelledError-caught branch — we want the finally to run even
        # under cancellation.
        with contextlib.suppress(Exception):
            await worker._coord.release_worker(worker.worker_id)


async def _build_worker() -> FreshnessWorker:
    """Wire the default worker from ``Settings`` + shared stores.

    Builds both memory and KB pipelines. When ``freshness_kb_enabled=False``
    the KB pipeline is still constructed but never receives jobs (the KB
    producer short-circuits before enqueue). Also wires a memory
    :class:`ScheduledScan` for the MTRNIX-316 safety-net scan.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metronix.freshness.coordination import CoordinationStore
    from metronix.freshness.decision_engine import build_default_decision_engine
    from metronix.freshness.scheduled_scan import ScheduledScan, SessionGCPass
    from metronix.freshness.stages.curator import Curator
    from metronix.freshness.stages.linker import Linker
    from metronix.freshness.stages.monitor import FreshnessMonitor
    from metronix.freshness.stages.reconciler import Reconciler
    from metronix.ingestion.freshness.target_raw_document import RawDocumentTarget
    from metronix.memory.freshness.target_memory import MemoryTarget
    from metronix.storage.freshness_pg import FreshnessStore
    from metronix.storage.memory_postgres import MemoryPostgresStore
    from metronix.storage.memory_qdrant import MemoryQdrantStore
    from metronix.storage.postgres import PostgresStore
    from metronix.storage.qdrant import AsyncQdrantVectorStore
    from metronix.storage.redis import RedisStore

    settings = get_settings()
    redis = RedisStore(settings.redis_url)
    coordination = CoordinationStore(redis=redis)
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    memory_pg_store = MemoryPostgresStore(engine)
    freshness_store = FreshnessStore(engine)

    # --- Memory pipeline ---
    _memory_qdrant_cache: dict[str, MemoryQdrantStore] = {}

    def memory_qdrant_factory(ws: str) -> MemoryQdrantStore:
        if ws not in _memory_qdrant_cache:
            _memory_qdrant_cache[ws] = MemoryQdrantStore(workspace_id=ws)
        return _memory_qdrant_cache[ws]

    memory_target = MemoryTarget(
        pg_store=memory_pg_store,
        qdrant_store_factory=memory_qdrant_factory,
    )

    memory_linker = Linker(
        target=memory_target,
        freshness_store=freshness_store,
        coordination=coordination,
        threshold=settings.freshness_linker_threshold,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    memory_reconciler = Reconciler(
        target=memory_target,
        freshness_store=freshness_store,
        coordination=coordination,
        threshold=settings.freshness_reconciler_threshold,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    memory_monitor = FreshnessMonitor(
        target=memory_target,
        freshness_store=freshness_store,
        coordination=coordination,
        stale_after_days=settings.freshness_stale_after_days,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    memory_curator = Curator(
        target=memory_target,
        freshness_store=freshness_store,
        coordination=coordination,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )

    # --- KB pipeline ---
    kb_pg_store = PostgresStore(settings.postgres_dsn)
    _kb_qdrant_cache: dict[str, AsyncQdrantVectorStore] = {}

    def kb_qdrant_factory(ws: str) -> AsyncQdrantVectorStore:
        if ws not in _kb_qdrant_cache:
            _kb_qdrant_cache[ws] = AsyncQdrantVectorStore(
                workspace_id=ws,
                host=settings.qdrant_host,
                port=settings.qdrant_http_port,
                api_key=settings.qdrant_api_key or None,
                https=settings.qdrant_https,
            )
        return _kb_qdrant_cache[ws]

    raw_doc_target = RawDocumentTarget(
        pg_store=kb_pg_store,
        qdrant_factory=kb_qdrant_factory,
    )

    kb_linker = Linker(
        target=raw_doc_target,
        freshness_store=freshness_store,
        coordination=coordination,
        threshold=settings.freshness_linker_threshold,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    kb_reconciler = Reconciler(
        target=raw_doc_target,
        freshness_store=freshness_store,
        coordination=coordination,
        threshold=settings.freshness_reconciler_threshold,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    kb_monitor = FreshnessMonitor(
        target=raw_doc_target,
        freshness_store=freshness_store,
        coordination=coordination,
        stale_after_days=settings.freshness_kb_stale_after_days,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )
    kb_curator = Curator(
        target=raw_doc_target,
        freshness_store=freshness_store,
        coordination=coordination,
        lock_ttl=settings.freshness_lock_ttl_seconds,
    )

    pipelines: dict[str, _Pipeline] = {
        "memory_record": _Pipeline(
            linker=memory_linker,
            reconciler=memory_reconciler,
            monitor=memory_monitor,
            curator=memory_curator,
            target=memory_target,
        ),
        "raw_document": _Pipeline(
            linker=kb_linker,
            reconciler=kb_reconciler,
            monitor=kb_monitor,
            curator=kb_curator,
            target=raw_doc_target,
        ),
    }

    # --- Scheduled scan (memory only in MTRNIX-316; KB deferred) ---
    scheduled_scanners: list[ScheduledScan] = []
    session_gc_passes: list[SessionGCPass] = []
    if settings.freshness_scheduled_scan_enabled:

        async def memory_workspace_lister() -> list[str]:
            # Enumerate workspaces via the memory PG store — SELECT DISTINCT
            # workspace_id FROM memory_records. Scoped by engine; never
            # leaks across tenants.
            return await memory_pg_store.list_workspaces()

        scheduled_scanners.append(
            ScheduledScan(
                target_kind="memory_record",
                target=memory_target,
                coordination=coordination,
                workspace_lister=memory_workspace_lister,
                stale_after_days=settings.freshness_stale_after_days,
                batch_limit=settings.freshness_scan_batch_limit,
            )
        )
        session_gc_passes.append(
            SessionGCPass(
                pg_store=memory_pg_store,
                workspace_lister=memory_workspace_lister,
                grace_hours=settings.memory_session_gc_grace_hours,
            )
        )

    return FreshnessWorker(
        coordination=coordination,
        freshness_pg=freshness_store,
        decision_engine=build_default_decision_engine(),
        pipelines=pipelines,
        worker_id=build_worker_id(),
        scheduled_scanners=scheduled_scanners,
        session_gc_passes=session_gc_passes,
        heartbeat_ttl=settings.freshness_heartbeat_ttl_seconds,
        reclaim_interval_iterations=settings.freshness_reclaim_interval_iterations,
        scheduled_scan_interval_seconds=settings.freshness_scheduled_scan_interval_seconds,
    )


async def main() -> None:
    """Entry point for ``python -m metronix.memory.freshness``."""
    logging.getLogger().setLevel(logging.INFO)
    settings = get_settings()
    if not settings.freshness_enabled:
        logger.info("freshness.disabled.exit")
        return
    logger.info(
        "freshness.worker.started",
        poll_seconds=settings.freshness_poll_seconds,
        max_jobs=settings.freshness_max_jobs_per_iteration,
        kb_enabled=settings.freshness_kb_enabled,
    )
    worker = await _build_worker()

    # Startup: tick heartbeat once so the processing-list lookup doesn't
    # discover us as dead, then one-shot reclaim of any orphaned peers,
    # then optional legacy-unprefixed drain when the operator explicitly
    # opts-in via METRONIX_FRESHNESS_DRAIN_LEGACY_AT_STARTUP=true.
    try:
        await worker._coord.tick_heartbeat(worker.worker_id, worker._heartbeat_ttl)
        await worker._reclaim_all_orphans()
        if settings.freshness_drain_legacy_at_startup:
            try:
                moved = await worker._coord.drain_legacy_unprefixed()
                logger.info(
                    "freshness.legacy.drain.startup_done",
                    moved=moved,
                )
            except Exception:
                logger.warning("freshness.legacy.drain.startup_failed", exc_info=True)
    except Exception:
        # Startup hooks are best-effort; never block the main loop.
        logger.warning("freshness.worker.startup_hooks_failed", exc_info=True)

    await _run_loop(worker)
