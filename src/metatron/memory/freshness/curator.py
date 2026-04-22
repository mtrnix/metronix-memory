"""Compat shim — moved to :mod:`metatron.freshness.stages.curator` (MTRNIX-313)."""

from __future__ import annotations

from metatron.freshness.stages.curator import Curator  # noqa: F401

__all__ = ["Curator"]
