"""Compat shim — moved to :mod:`metronix.freshness.stages.curator` (MTRNIX-313)."""

from __future__ import annotations

from metronix.freshness.stages.curator import Curator  # noqa: F401

__all__ = ["Curator"]
