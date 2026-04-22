"""Compat shim — moved to :mod:`metatron.freshness.stages.linker` (MTRNIX-313)."""

from __future__ import annotations

from metatron.freshness.stages.linker import Linker, link_memory_items_batch  # noqa: F401

__all__ = ["Linker", "link_memory_items_batch"]
