"""Unit tests for Curator stage (MTRNIX-304, updated for MTRNIX-313).

Phase B rewires Curator through the :class:`MemoryTarget` adapter, but the
behavioural contract is unchanged for memory records. These tests still drive
a mocked ``MemoryPostgresStore`` — the adapter is a thin translator so the
original assertions hold byte-for-byte on the memory path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import LifecycleStatus, MemoryRecord, MemoryScope
from metatron.memory.freshness.curator import Curator
from metatron.memory.freshness.target_memory import MemoryTarget


def _record(**overrides: object) -> MemoryRecord:
    defaults = {
        "id": "rec1",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "content": "candidate memory",
        "status": LifecycleStatus.CANDIDATE,
        "evidence_count": 1,
        "created_at": datetime(2026, 4, 20, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _build_curator() -> tuple[Curator, MagicMock, AsyncMock, AsyncMock]:
    pg = MagicMock()
    pg.get = AsyncMock()
    pg.update_lifecycle = AsyncMock()
    qdrant = MagicMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)
    coordination = AsyncMock()
    freshness_store = AsyncMock()
    curator = Curator(
        target=target,
        freshness_store=freshness_store,
        coordination=coordination,
    )
    return curator, pg, coordination, freshness_store


class TestCurator:
    async def test_candidate_with_evidence_promotes_to_active(self) -> None:
        curator, pg, coord, _fs = _build_curator()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()

        result = await curator.run("ws1", "rec1")

        assert result is LifecycleStatus.ACTIVE
        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["status"] == LifecycleStatus.ACTIVE
        assert kwargs["append_tag"] == "auto_curated"

    async def test_candidate_with_zero_evidence_untouched(self) -> None:
        curator, pg, coord, _fs = _build_curator()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(evidence_count=0)

        result = await curator.run("ws1", "rec1")

        assert result is None
        pg.update_lifecycle.assert_not_awaited()

    async def test_non_candidate_is_noop(self) -> None:
        curator, pg, coord, _fs = _build_curator()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(
            status=LifecycleStatus.ACTIVE,
            tags=["auto_curated"],
        )

        result = await curator.run("ws1", "rec1")

        assert result is None
        pg.update_lifecycle.assert_not_awaited()

    async def test_lock_contention_returns_none(self) -> None:
        curator, pg, coord, _fs = _build_curator()
        coord.acquire_lock.return_value = None

        result = await curator.run("ws1", "rec1")

        assert result is None
        pg.get.assert_not_awaited()
