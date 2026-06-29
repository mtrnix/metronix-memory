"""Curator short-circuits when the target does not support candidate promotion.

MTRNIX-313: KB raw_documents have no CANDIDATE state in Phase B, so the
Curator must exit without acquiring a lock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from metronix.freshness.stages.curator import Curator


async def test_kb_curator_short_circuits_without_lock() -> None:
    target = MagicMock()
    target.kind = "raw_document"
    target.supports_candidate_promotion = False
    target.get = AsyncMock()
    target.update_lifecycle = AsyncMock()

    coord = AsyncMock()
    coord.acquire_lock = AsyncMock()
    coord.release = AsyncMock()

    curator = Curator(
        target=target,
        freshness_store=AsyncMock(),
        coordination=coord,
    )

    result = await curator.run("ws", "doc-1")

    assert result is None
    # Short-circuit invariant: no lock request was made — this is the
    # performance guarantee for bulk KB jobs.
    coord.acquire_lock.assert_not_awaited()
    target.get.assert_not_awaited()
    target.update_lifecycle.assert_not_awaited()
