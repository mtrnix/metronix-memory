"""Unit tests for Linker stage (MTRNIX-304, updated for MTRNIX-313).

Phase B rewires Linker through :class:`MemoryTarget`. The stage stays
behaviourally identical for memory; tests drive the adapter-wrapped stage
and patch the storage-layer graph helper since the adapter now goes
through it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metronix.core.models import MemoryRecord, MemoryScope
from metronix.memory.freshness.linker import Linker
from metronix.memory.freshness.target_memory import MemoryTarget


def _record(**overrides: object) -> MemoryRecord:
    defaults = {
        "id": "rec1",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "content": "Payment integration with Stripe uses webhook X.",
        "created_at": datetime(2026, 4, 20, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _build_linker(
    threshold: float = 0.6,
) -> tuple[Linker, MagicMock, AsyncMock, AsyncMock, AsyncMock]:
    pg = MagicMock()
    pg.get = AsyncMock()
    pg.update_lifecycle = AsyncMock()
    qdrant = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)
    coordination = AsyncMock()
    freshness_store = AsyncMock()
    linker = Linker(
        target=target,
        freshness_store=freshness_store,
        coordination=coordination,
        threshold=threshold,
    )
    return linker, pg, qdrant, coordination, freshness_store


# The ``MemoryTarget.link_edges_batch`` path goes through
# ``metronix.storage.memory_graph.link_memory_items_batch`` via
# ``asyncio.to_thread``. Patch there to intercept the batch call.
_LINK_BATCH_PATH = "metronix.storage.memory_graph.link_memory_items_batch"


class TestLinker:
    async def test_returns_zero_when_record_missing(self) -> None:
        linker, pg, qdrant, coord, _fs = _build_linker()
        pg.get.return_value = None
        coord.acquire_lock.return_value = "tok"

        count = await linker.run("ws1", "missing")

        assert count == 0
        qdrant.search.assert_not_awaited()
        pg.update_lifecycle.assert_not_awaited()

    async def test_lock_contention_returns_zero(self) -> None:
        linker, pg, qdrant, coord, _fs = _build_linker()
        coord.acquire_lock.return_value = None

        count = await linker.run("ws1", "rec1")

        assert count == 0
        pg.get.assert_not_awaited()
        qdrant.search.assert_not_awaited()

    async def test_counts_hits_above_threshold(self) -> None:
        linker, pg, qdrant, coord, fs = _build_linker(threshold=0.6)
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [
            {"record_id": "rec1", "score": 1.0},
            {"record_id": "rec2", "score": 0.72},
            {"record_id": "rec3", "score": 0.65},
            {"record_id": "rec4", "score": 0.50},
        ]

        with patch(_LINK_BATCH_PATH, return_value=None) as mock_link:
            count = await linker.run("ws1", "rec1")

        assert count == 2
        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["evidence_count"] == 2
        # The batch helper must be called exactly ONCE with all edges —
        # not N times, not per-edge. Thread-pool-pressure guard.
        assert mock_link.call_count == 1
        call_args = mock_link.call_args.args
        assert call_args[0] == "ws1"
        edges = call_args[1]
        assert len(edges) == 2
        assert {edge[1] for edge in edges} == {"rec2", "rec3"}
        # Workspace isolation on update.
        args = pg.update_lifecycle.await_args.args
        assert args[0] == "ws1"
        assert args[1] == "rec1"
        fs.save_machine_event.assert_awaited()

    async def test_no_matches_still_updates_evidence_to_zero(self) -> None:
        linker, pg, qdrant, coord, _fs = _build_linker()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [{"record_id": "rec1", "score": 1.0}]

        with patch(_LINK_BATCH_PATH, return_value=None) as mock_link:
            count = await linker.run("ws1", "rec1")

        assert count == 0
        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["evidence_count"] == 0
        # No edges → batch helper is skipped entirely.
        mock_link.assert_not_called()

    async def test_neo4j_failure_is_swallowed(self) -> None:
        linker, pg, qdrant, coord, _fs = _build_linker()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [{"record_id": "rec2", "score": 0.9}]

        with patch(_LINK_BATCH_PATH, side_effect=RuntimeError("neo4j down")):
            # Graph failures must not fail the stage.
            count = await linker.run("ws1", "rec1")

        assert count == 1
        pg.update_lifecycle.assert_awaited_once()

    async def test_release_always_called(self) -> None:
        linker, pg, qdrant, coord, _fs = _build_linker()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.side_effect = RuntimeError("qdrant boom")

        with pytest.raises(RuntimeError, match="qdrant boom"):
            await linker.run("ws1", "rec1")

        coord.release.assert_awaited_once()
        # Signature: (stage, target_id, token, *, target_kind="")
        args = coord.release.await_args.args
        kwargs = coord.release.await_args.kwargs
        assert args == ("linker", "rec1", "tok")
        assert kwargs.get("target_kind") == "memory_record"
