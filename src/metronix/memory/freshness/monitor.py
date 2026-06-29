"""Compat shim — moved to :mod:`metronix.freshness.stages.monitor` (MTRNIX-313)."""

from __future__ import annotations

from metronix.freshness.stages.monitor import FreshnessMonitor  # noqa: F401

__all__ = ["FreshnessMonitor"]
