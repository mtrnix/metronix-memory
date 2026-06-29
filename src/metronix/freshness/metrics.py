"""Prometheus metrics stubs for the freshness worker.

Moved from ``metronix.memory.freshness.metrics`` in Phase B (MTRNIX-313) so
the counters serve both memory and KB pipelines.

The ``prometheus_client`` package is *not* a runtime dependency. When it is
available, real counters/gauges/histograms are exposed; when missing, no-op
stubs keep the worker importable and functional (MachineEvents + structlog
carry the observability load in absence of Prometheus).
"""

from __future__ import annotations

from typing import Any


class _NoopMetric:
    """Drop-in Counter/Gauge/Histogram replacement."""

    def labels(self, **_kwargs: Any) -> _NoopMetric:
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None


jobs_total: Any
queue_depth_gauge: Any
stage_duration: Any
decision_confidence: Any
worker_errors: Any
qdrant_sync_failed: Any
orphans_reclaimed: Any
reclaim_errors: Any
scheduled_scan_jobs_enqueued: Any
scheduled_scan_errors: Any
legacy_keys_drained: Any
memory_session_gc_deleted: Any
memory_session_gc_errors: Any

try:
    from prometheus_client import (  # type: ignore[import-not-found]
        Counter,
        Gauge,
        Histogram,
    )

    jobs_total = Counter(
        "freshness_jobs_total",
        "Freshness jobs processed",
        ["status", "workspace_id"],
    )
    queue_depth_gauge = Gauge(
        "freshness_queue_depth",
        "Redis queue depth",
        ["workspace_id"],
    )
    stage_duration = Histogram(
        "freshness_stage_duration_seconds",
        "Per-stage duration in seconds",
        ["stage"],
    )
    decision_confidence = Histogram(
        "freshness_decision_confidence",
        "DecisionEngine confidence distribution",
        buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    )
    worker_errors = Counter(
        "freshness_worker_errors_total",
        "Worker iteration errors",
        ["stage"],
    )
    qdrant_sync_failed = Counter(
        "freshness_qdrant_sync_failed_total",
        "Best-effort Qdrant payload sync failures from the freshness pipeline",
        ["target_kind", "stage"],
    )
    orphans_reclaimed = Counter(
        "freshness_orphans_reclaimed_total",
        "Jobs moved from a dead-worker processing list back to the queue (MTRNIX-316)",
        ["env", "worker_id_hash"],
    )
    reclaim_errors = Counter(
        "freshness_reclaim_errors_total",
        "Reclaim pass failures (MTRNIX-316)",
        ["env", "stage"],
    )
    scheduled_scan_jobs_enqueued = Counter(
        "freshness_scheduled_scan_jobs_enqueued_total",
        "Records enqueued by the scheduled-scan safety net (MTRNIX-316)",
        ["env", "target_kind"],
    )
    scheduled_scan_errors = Counter(
        "freshness_scheduled_scan_errors_total",
        "Scheduled-scan failures (MTRNIX-316)",
        ["env", "target_kind"],
    )
    legacy_keys_drained = Counter(
        "freshness_legacy_keys_drained_total",
        "Legacy unprefixed queue entries drained into env-prefixed keys (MTRNIX-316)",
        ["env"],
    )
    memory_session_gc_deleted = Counter(
        "memory_session_gc_deleted_total",
        "Session memory records deleted by the GC pass (phase-2 memory-scopes)",
        ["env"],
    )
    memory_session_gc_errors = Counter(
        "memory_session_gc_errors_total",
        "Per-workspace errors in the session GC pass",
        ["env"],
    )
except ImportError:  # pragma: no cover — real branch when dep missing
    jobs_total = _NoopMetric()
    queue_depth_gauge = _NoopMetric()
    stage_duration = _NoopMetric()
    decision_confidence = _NoopMetric()
    worker_errors = _NoopMetric()
    qdrant_sync_failed = _NoopMetric()
    orphans_reclaimed = _NoopMetric()
    reclaim_errors = _NoopMetric()
    scheduled_scan_jobs_enqueued = _NoopMetric()
    scheduled_scan_errors = _NoopMetric()
    legacy_keys_drained = _NoopMetric()
    memory_session_gc_deleted = _NoopMetric()
    memory_session_gc_errors = _NoopMetric()


__all__ = [
    "decision_confidence",
    "jobs_total",
    "legacy_keys_drained",
    "memory_session_gc_deleted",
    "memory_session_gc_errors",
    "orphans_reclaimed",
    "qdrant_sync_failed",
    "queue_depth_gauge",
    "reclaim_errors",
    "scheduled_scan_errors",
    "scheduled_scan_jobs_enqueued",
    "stage_duration",
    "worker_errors",
]
