"""MemoryTarget adapter conformance tests (MTRNIX-313)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from metatron.core.models import LifecycleStatus, MemoryRecord, MemoryScope
from metatron.memory.freshness.target_memory import MemoryTarget


def _record(**overrides: object) -> MemoryRecord:
    defaults = {
        "id": "rec1",
        "workspace_id": "ws",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "content": "hello",
        "status": LifecycleStatus.ACTIVE,
        "freshness_score": 0.5,
        "evidence_count": 0,
        "created_at": datetime(2026, 4, 20, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


async def test_kind_and_supports_promotion() -> None:
    pg = MagicMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())
    assert target.kind == "memory_record"
    assert target.supports_candidate_promotion is True


async def test_get_returns_freshness_target_record() -> None:
    pg = MagicMock()
    pg.get = AsyncMock(return_value=_record())
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())

    rec = await target.get("ws", "rec1")

    assert rec is not None
    assert rec.target_id == "rec1"
    assert rec.workspace_id == "ws"
    assert rec.content == "hello"
    assert rec.status is LifecycleStatus.ACTIVE
    assert rec.agent_id == "agent1"


async def test_get_returns_none_when_record_missing() -> None:
    pg = MagicMock()
    pg.get = AsyncMock(return_value=None)
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())

    rec = await target.get("ws", "missing")

    assert rec is None


async def test_update_lifecycle_passes_status_and_score() -> None:
    pg = MagicMock()
    pg.update_lifecycle = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())

    await target.update_lifecycle(
        "ws",
        "rec1",
        status=LifecycleStatus.STALE,
        freshness_score=0.25,
    )

    pg.update_lifecycle.assert_awaited_once()
    kwargs = pg.update_lifecycle.await_args.kwargs
    assert kwargs["status"] is LifecycleStatus.STALE
    assert kwargs["freshness_score"] == 0.25


async def test_update_lifecycle_splits_comma_joined_append_tag() -> None:
    """apply_decision joins tags with ','; adapter must split back into list."""
    pg = MagicMock()
    pg.update_lifecycle = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())

    await target.update_lifecycle(
        "ws",
        "rec1",
        append_tag="a,b,c",
    )

    kwargs = pg.update_lifecycle.await_args.kwargs
    assert kwargs["append_tags"] == ["a", "b", "c"]
    # Single-tag form stays single.


async def test_update_lifecycle_passes_single_tag_as_append_tag() -> None:
    pg = MagicMock()
    pg.update_lifecycle = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())

    await target.update_lifecycle(
        "ws",
        "rec1",
        append_tag="auto_curated",
    )

    kwargs = pg.update_lifecycle.await_args.kwargs
    assert kwargs["append_tag"] == "auto_curated"
    assert kwargs.get("append_tags") is None


async def test_similarity_search_filters_empty_record_ids() -> None:
    pg = MagicMock()
    qdrant = AsyncMock()
    qdrant.search = AsyncMock(
        return_value=[
            {"record_id": "r1", "score": 0.9, "content": "a"},
            {"record_id": "", "score": 0.8},  # filtered
            {"record_id": "r2", "score": 0.7, "content": "b"},
        ]
    )
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)

    hits = await target.similarity_search("ws", "query", top_k=10)

    assert [h.target_id for h in hits] == ["r1", "r2"]
    assert hits[0].score == 0.9


async def test_link_edges_batch_is_best_effort_on_neo4j_failure() -> None:
    pg = MagicMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())

    with patch(
        "metatron.storage.memory_graph.link_memory_items_batch",
        side_effect=RuntimeError("neo4j down"),
    ):
        # Must not raise — failures are swallowed.
        await target.link_edges_batch("ws", "rec1", [("rec2", 0.9)])


async def test_sync_downstream_stores_writes_status_payload() -> None:
    """MTRNIX-322: adapter now mirrors PG status onto the Qdrant payload."""
    pg = MagicMock()
    qdrant = AsyncMock()
    qdrant.update_payload = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: qdrant)

    result = await target.sync_downstream_stores(
        "ws",
        "rec1",
        status=LifecycleStatus.ARCHIVED,
        freshness_score=0.0,
    )

    assert result is None
    qdrant.update_payload.assert_awaited_once_with("rec1", {"status": "archived"})
