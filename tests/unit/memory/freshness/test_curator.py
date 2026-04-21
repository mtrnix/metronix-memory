"""Unit tests for Curator stage (MTRNIX-304)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import MemoryRecord, MemoryScope, MemoryStatus
from metatron.memory.freshness.curator import Curator


def _record(**overrides: object) -> MemoryRecord:
    defaults = {
        "id": "rec1",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "content": "candidate memory",
        "status": MemoryStatus.CANDIDATE,
        "evidence_count": 1,
        "created_at": datetime(2026, 4, 20, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _build_curator() -> tuple[Curator, MagicMock, AsyncMock, AsyncMock]:
    pg = MagicMock()
    pg.get = AsyncMock()
    pg.update_lifecycle = AsyncMock()
    coordination = AsyncMock()
    freshness_pg = AsyncMock()
    curator = Curator(
        pg_store=pg,
        freshness_pg=freshness_pg,
        coordination=coordination,
    )
    return curator, pg, coordination, freshness_pg


class TestCurator:
    async def test_candidate_with_evidence_promotes_to_active(self) -> None:
        curator, pg, coord, _fp = _build_curator()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record()

        result = await curator.run("ws1", "rec1")

        assert result is MemoryStatus.ACTIVE
        pg.update_lifecycle.assert_awaited_once()
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["status"] == MemoryStatus.ACTIVE
        assert kwargs["append_tag"] == "auto_curated"

    async def test_candidate_with_zero_evidence_untouched(self) -> None:
        curator, pg, coord, _fp = _build_curator()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(evidence_count=0)

        result = await curator.run("ws1", "rec1")

        assert result is None
        pg.update_lifecycle.assert_not_awaited()

    async def test_non_candidate_is_noop(self) -> None:
        curator, pg, coord, _fp = _build_curator()
        coord.acquire_lock.return_value = "tok"
        pg.get.return_value = _record(
            status=MemoryStatus.ACTIVE,
            tags=["auto_curated"],
        )

        result = await curator.run("ws1", "rec1")

        assert result is None
        pg.update_lifecycle.assert_not_awaited()

    async def test_lock_contention_returns_none(self) -> None:
        curator, pg, coord, _fp = _build_curator()
        coord.acquire_lock.return_value = None

        result = await curator.run("ws1", "rec1")

        assert result is None
        pg.get.assert_not_awaited()
