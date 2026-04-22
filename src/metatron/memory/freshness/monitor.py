"""Compat shim — moved to :mod:`metatron.freshness.stages.monitor` (MTRNIX-313)."""

from __future__ import annotations

from metatron.freshness.stages.monitor import FreshnessMonitor  # noqa: F401

__all__ = ["FreshnessMonitor"]
