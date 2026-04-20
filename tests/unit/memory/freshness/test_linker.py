"""Unit tests for Linker stage (MTRNIX-304)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.memory.freshness.linker import Linker


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
    coordination = AsyncMock()
    freshness_pg = AsyncMock()
    linker = Linker(
        pg_store=pg,
        qdrant_store_factory=lambda _ws: qdrant,
        freshness_pg=freshness_pg,
        coordination=coordination,
        threshold=threshold,
    )
    return linker, pg, qdrant, coordination, freshness_pg


class TestLinker:
    async def test_returns_zero_when_record_missing(self) -> None:
        linker, pg, qdrant, coord, _fp = _build_linker()
        pg.get.return_value = None
        coord.acquire_lock.return_value = "tok"

        count = await linker.run("ws1", "missing")

        assert count == 0
        qdrant.search.assert_not_awaited()
        pg.update_lifecycle.assert_not_awaited()

    async def test_lock_contention_returns_zero(self) -> None:
        linker, pg, qdrant, coord, _fp = _build_linker()
        coord.acquire_lock.return_value = None

        count = await linker.run("ws1", "rec1")

        assert count == 0
        pg.get.assert_not_awaited()
        qdrant.search.assert_not_awaited()

    async def test_counts_hits_above_threshold(self) -> None:
        linker, pg, qdrant, coord, fp = _build_linker(threshold=0.6)
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        # Self-hit (score 1.0) must be excluded; two real matches above
        # threshold and one below.
        qdrant.search.return_value = [
            {"record_id": "rec1", "score": 1.0},
            {"record_id": "rec2", "score": 0.72},
            {"record_id": "rec3", "score": 0.65},
            {"record_id": "rec4", "score": 0.50},
        ]

        with patch(
            "metatron.memory.freshness.linker.link_memory_items",
            return_value=None,
        ) as mock_link:
            count = await linker.run("ws1", "rec1")

        assert count == 2
        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["evidence_count"] == 2
        assert mock_link.call_count == 2
        # Workspace isolation on update
        args = pg.update_lifecycle.await_args.args
        assert args[0] == "ws1"
        assert args[1] == "rec1"
        fp.save_machine_event.assert_awaited()

    async def test_no_matches_still_updates_evidence_to_zero(self) -> None:
        linker, pg, qdrant, coord, _fp = _build_linker()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [{"record_id": "rec1", "score": 1.0}]

        with patch(
            "metatron.memory.freshness.linker.link_memory_items",
            return_value=None,
        ):
            count = await linker.run("ws1", "rec1")

        assert count == 0
        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["evidence_count"] == 0

    async def test_neo4j_failure_is_swallowed(self) -> None:
        linker, pg, qdrant, coord, _fp = _build_linker()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.return_value = [
            {"record_id": "rec2", "score": 0.9},
        ]

        with patch(
            "metatron.memory.freshness.linker.link_memory_items",
            side_effect=RuntimeError("neo4j down"),
        ):
            # Graph failures must not fail the stage.
            count = await linker.run("ws1", "rec1")

        assert count == 1
        pg.update_lifecycle.assert_awaited_once()

    async def test_release_always_called(self) -> None:
        linker, pg, qdrant, coord, _fp = _build_linker()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()
        qdrant.search.side_effect = RuntimeError("qdrant boom")

        with pytest.raises(RuntimeError, match="qdrant boom"):
            await linker.run("ws1", "rec1")

        coord.release.assert_awaited_once()
        args = coord.release.await_args.args
        assert args == ("linker", "rec1", "tok")
