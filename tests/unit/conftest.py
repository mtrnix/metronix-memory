"""Unit-test-level fixtures."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_lru_caches() -> None:
    """Clear module-level LRU caches between tests to prevent cross-test contamination."""
    from metatron.retrieval.channels import _cached_get_graph_entities

    _cached_get_graph_entities.cache_clear()
