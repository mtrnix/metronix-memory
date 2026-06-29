"""Compat shim — this module was renamed to ``freshness_pg`` (MTRNIX-313).

Phase A called the store ``FreshnessPostgresStore`` and lived here. Phase B
renames the store to :class:`~metronix.storage.freshness_pg.FreshnessStore`
and moves it one level up since it now serves both memory and KB review
queues. Do NOT add new code here. Import from
:mod:`metronix.storage.freshness_pg` instead.
"""

from __future__ import annotations

from metronix.storage.freshness_pg import (  # noqa: F401
    FreshnessPostgresStore,
    FreshnessStore,
)

__all__ = ["FreshnessPostgresStore", "FreshnessStore"]
