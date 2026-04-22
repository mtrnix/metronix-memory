"""FreshnessWorker — polling loop that drives the freshness pipeline.

One ``run_once`` iteration:

1. Enumerate active workspaces.
2. ``dequeue_batch`` per workspace.
3. For each job:
   * Log ``freshness_job_received`` MachineEvent (with ``target_kind``).
   * Dispatch to the pipeline matching ``job.target_kind``.
   * Linker → Reconciler → Monitor → Curator.
   * If the record still exists and is eligible, call ``DecisionEngine``
     + ``apply_decision`` through the target adapter.
   * Log ``freshness_job_processed`` MachineEvent.

``main()`` wraps ``run_once`` in a bounded error-backoff loop and exits
immediately when ``freshness_enabled=False``.

Workspace isolation: every stage call receives ``job.workspace_id``
directly; the worker never assumes a default.

Phase B (MTRNIX-313): the worker hosts *two* pipeline stacks (memory + KB)
and routes jobs on ``target_kind``. When the KB flag is off and no KB jobs
are ever enqueued, the memory path is byte-identical to Phase A.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob, LifecycleStatus, MachineEvent
from metatron.freshness import metrics

if TYPE_CHECKING:
    from metatron.freshness.coordination import CoordinationStore
    from metatron.freshness.decision_engine import DecisionEngine
    from metatron.freshness.stages.curator import Curator
    from metatron.freshness.stages.linker import Linker
    from metatron.freshness.stages.monitor import FreshnessMonitor
    from metatron.freshness.stages.reconciler import Reconciler
    from metatron.freshness.targets import FreshnessTarget
    from metatron.storage.freshness_pg import FreshnessStore

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

    async def run_once(self, max_jobs: int) -> int:
        """Dequeue + process up to ``max_jobs`` per workspace."""
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
        target_id = job.target_id
        target_kind = job.target_kind or "memory_record"
        started = time.monotonic()

        pipeline = self._pipelines.get(target_kind)
        if pipeline is None:
            logger.warning(
                "freshness.worker.unknown_target_kind",
                workspace_id=ws,
                target_kind=target_kind,
                target_id=target_id,
            )
            # Still audit the skip so operators see the poison job in the log.
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
            # We only log the receipt; lifecycle work for deleted records
            # is out of scope.
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
            return

        decision_action = "skipped_missing"
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
                from metatron.freshness.apply_decision import apply_decision

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
    """Wire the default worker from ``Settings`` + shared stores.

    Builds both memory and KB pipelines. When ``freshness_kb_enabled=False``
    the KB pipeline is still constructed but never receives jobs (the KB
    producer short-circuits before enqueue).
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.freshness.coordination import CoordinationStore
    from metatron.freshness.decision_engine import build_default_decision_engine
    from metatron.freshness.stages.curator import Curator
    from metatron.freshness.stages.linker import Linker
    from metatron.freshness.stages.monitor import FreshnessMonitor
    from metatron.freshness.stages.reconciler import Reconciler
    from metatron.ingestion.freshness.target_raw_document import RawDocumentTarget
    from metatron.memory.freshness.target_memory import MemoryTarget
    from metatron.storage.freshness_pg import FreshnessStore
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore
    from metatron.storage.postgres import PostgresStore
    from metatron.storage.qdrant import AsyncQdrantVectorStore
    from metatron.storage.redis import RedisStore

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
        # AsyncQdrantVectorStore is async under the hood (collection
        # ensured on first call) but the constructor is sync. Cache one
        # instance per workspace so repeated similarity searches reuse it.
        if ws not in _kb_qdrant_cache:
            _kb_qdrant_cache[ws] = AsyncQdrantVectorStore(
                workspace_id=ws,
                host=settings.qdrant_host,
                port=settings.qdrant_port,
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

    return FreshnessWorker(
        coordination=coordination,
        freshness_pg=freshness_store,
        decision_engine=build_default_decision_engine(),
        pipelines=pipelines,
    )


# Kept for type-hint compatibility with Phase A call sites that imported
# these callable aliases (e.g. external tests mocking via the old type).
PgStoreFactory = Callable[[str], "MemoryPostgresStore"]  # noqa: F821
QdrantStoreFactory = Callable[[str], "MemoryQdrantStore"]  # noqa: F821


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
        kb_enabled=settings.freshness_kb_enabled,
    )
    worker = await _build_worker()
    await _run_loop(worker)
