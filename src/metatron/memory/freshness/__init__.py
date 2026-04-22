"""Freshness pipeline for agent memory (MTRNIX-304, WS1 Phase A).

Entry points:
* ``CoordinationStore`` — Redis-backed per-workspace queue + per-stage locks.
* ``enqueue_if_enabled`` — producer hook called by memory writers.
* ``FreshnessWorker`` — bounded polling loop that runs all five stages.

The worker is opt-in. Setting ``METATRON_FRESHNESS_ENABLED=false`` (the
default) makes the producer a no-op and the worker exit immediately,
so the module is safe to leave imported in existing code paths.
"""

from __future__ import annotations

from metatron.memory.freshness.coordination import CoordinationStore, queue_key_for

__all__ = [
    "CoordinationStore",
    "queue_key_for",
]
