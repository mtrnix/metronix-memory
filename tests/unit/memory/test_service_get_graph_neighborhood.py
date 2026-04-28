"""Unit tests for MemoryService.get_graph_neighborhood (MTRNIX-324)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.memory.service import MemoryService


def _make_service(workspace_id: str = "ws-1") -> tuple[MemoryService, AsyncMock, AsyncMock]:
    """Return a minimal MemoryService wired with mocked stores."""
    pg_store = AsyncMock()
    redis_cache = AsyncMock()
    qdrant_store = AsyncMock()
    service = MemoryService(
        redis_cache=redis_cache,
        qdrant_store=qdrant_store,
        pg_store=pg_store,
        workspace_id=workspace_id,
    )
    return service, pg_store, qdrant_store


def _sample_record(record_id: str = "mem-1", workspace_id: str = "ws-1") -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id=workspace_id,
        agent_id="agent-1",
        scope=MemoryScope.PER_AGENT,
        source_type="conversation",
        content="test content",
        tags=[],
        importance_score=0.5,
        ttl_expires_at=None,
        content_hash="hash-abc",
        session_id=None,
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestGetGraphNeighborhoodService:
    async def test_workspace_mismatch_raises(self) -> None:
        """Service bound to ws-A; called with ws-B ⇒ ValueError."""
        service, _, _ = _make_service("ws-A")
        with pytest.raises(ValueError, match="workspace_id mismatch"):
            await service.get_graph_neighborhood("ws-B", "seed-id")

    async def test_depth_zero_raises(self) -> None:
        """depth=0 is invalid."""
        service, _, _ = _make_service("ws-1")
        with pytest.raises(ValueError, match="depth"):
            await service.get_graph_neighborhood("ws-1", "seed-id", depth=0)

    async def test_depth_four_raises(self) -> None:
        """depth=4 exceeds the max of 3."""
        service, _, _ = _make_service("ws-1")
        with pytest.raises(ValueError, match="depth"):
            await service.get_graph_neighborhood("ws-1", "seed-id", depth=4)

    async def test_neo4j_down_returns_seed_from_pg(self) -> None:
        """When Neo4j is unavailable, service returns ([seed], []) from PG."""
        service, pg_store, _ = _make_service("ws-1")
        seed = _sample_record("seed-id")
        pg_store.get.return_value = seed

        with patch(
            "metatron.memory.service.get_memory_neighborhood",
            side_effect=OSError("connection refused"),
        ):
            records, edges = await service.get_graph_neighborhood("ws-1", "seed-id")

        assert len(edges) == 0
        assert len(records) == 1
        assert records[0].id == "seed-id"

    async def test_filters_to_pg_truth(self) -> None:
        """Neo4j returns ids A, B, C; PG only has A and C ⇒ result drops B."""
        service, pg_store, _ = _make_service("ws-1")

        def _pg_get(ws: str, rid: str) -> MemoryRecord | None:
            if rid in ("seed-A", "rec-C"):
                return _sample_record(rid, ws)
            return None  # rec-B is absent in PG

        pg_store.get.side_effect = _pg_get

        neighborhood = {
            "record_ids": ["seed-A", "rec-B", "rec-C"],
            "edges": [
                {"source": "seed-A", "target": "rec-B", "type": "REMEMBERS", "metadata": None},
                {"source": "seed-A", "target": "rec-C", "type": "LINKED_TO", "metadata": None},
            ],
        }

        with patch(
            "metatron.memory.service.get_memory_neighborhood",
            return_value=neighborhood,
        ):
            records, edges = await service.get_graph_neighborhood("ws-1", "seed-A")

        record_ids_returned = {r.id for r in records}
        assert "seed-A" in record_ids_returned
        assert "rec-C" in record_ids_returned
        assert "rec-B" not in record_ids_returned
        # Edges are returned as-is (PG filtering applies to records, not edges)
        assert len(edges) == 2

    async def test_seed_always_included_when_pg_has_it(self) -> None:
        """Seed must be first in the returned records list."""
        service, pg_store, _ = _make_service("ws-1")
        seed = _sample_record("seed-id")
        pg_store.get.return_value = seed

        neighborhood = {
            "record_ids": ["seed-id"],
            "edges": [],
        }

        with patch(
            "metatron.memory.service.get_memory_neighborhood",
            return_value=neighborhood,
        ):
            records, edges = await service.get_graph_neighborhood("ws-1", "seed-id")

        assert records[0].id == "seed-id"
        assert edges == []
