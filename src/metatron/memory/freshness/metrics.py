"""Compat shim — moved to :mod:`metatron.freshness.metrics` (MTRNIX-313)."""

from __future__ import annotations

from metatron.freshness.metrics import (  # noqa: F401
    decision_confidence,
    jobs_total,
    legacy_keys_drained,
    orphans_reclaimed,
    qdrant_sync_failed,
    queue_depth_gauge,
    reclaim_errors,
    scheduled_scan_errors,
    scheduled_scan_jobs_enqueued,
    stage_duration,
    worker_errors,
)

__all__ = [
    "decision_confidence",
    "jobs_total",
    "legacy_keys_drained",
    "orphans_reclaimed",
    "qdrant_sync_failed",
    "queue_depth_gauge",
    "reclaim_errors",
    "scheduled_scan_errors",
    "scheduled_scan_jobs_enqueued",
    "stage_duration",
    "worker_errors",
]
