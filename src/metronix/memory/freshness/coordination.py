"""Compat shim — moved to :mod:`metronix.freshness.coordination` (MTRNIX-313).

Phase A kept coordination primitives under ``memory.freshness``. In Phase B
the queue and locks serve both memory and KB pipelines so they were
promoted one level. Do NOT add new code here; import from
:mod:`metronix.freshness.coordination` instead.
"""

from __future__ import annotations

from metronix.freshness.coordination import (  # noqa: F401
    CoordinationStore,
    queue_key_for,
)

__all__ = ["CoordinationStore", "queue_key_for"]
