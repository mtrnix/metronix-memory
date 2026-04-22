"""Compat shim — moved to :mod:`metatron.freshness.stages.reconciler` (MTRNIX-313)."""

from __future__ import annotations

from metatron.freshness.stages.reconciler import (  # noqa: F401
    Reconciler,
    alias_link_memory_items,
)

__all__ = ["Reconciler", "alias_link_memory_items"]
