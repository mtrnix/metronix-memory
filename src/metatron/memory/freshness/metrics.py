"""Prometheus metrics stubs for the freshness worker (MTRNIX-304).

The ``prometheus_client`` package is *not* a runtime dependency in this
phase. When it is available, real counters/gauges/histograms are exposed;
when missing, no-op stubs keep the worker importable and functional
(MachineEvents + structlog carry the observability load for Phase A).
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
except ImportError:  # pragma: no cover — real branch when dep missing
    jobs_total = _NoopMetric()
    queue_depth_gauge = _NoopMetric()
    stage_duration = _NoopMetric()
    decision_confidence = _NoopMetric()
    worker_errors = _NoopMetric()


__all__ = [
    "decision_confidence",
    "jobs_total",
    "queue_depth_gauge",
    "stage_duration",
    "worker_errors",
]
