"""Compat shim — moved to :mod:`metatron.freshness.metrics` (MTRNIX-313)."""

from __future__ import annotations

from metatron.freshness.metrics import (  # noqa: F401
    decision_confidence,
    jobs_total,
    queue_depth_gauge,
    stage_duration,
    worker_errors,
)

__all__ = [
    "decision_confidence",
    "jobs_total",
    "queue_depth_gauge",
    "stage_duration",
    "worker_errors",
]
