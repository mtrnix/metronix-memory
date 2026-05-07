"""Tests for MemorySearchService (WS1 Stage 3)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.memory.search import MemorySearchService, MemorySearchWeights


def _qdrant_hit(
    record_id: str,
    content: str = "",
    score: float = 1.0,
    agent_id: str = "agent1",
    scope: str = "per_agent",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "record_id": record_id,
        "content": content,
        "workspace_id": "ws1",
        "agent_id": agent_id,
        "scope": scope,
        "tags": tags or [],
        "source_type": "chat",
        "importance_score": 0.5,
    }
    return {
        "record_id": record_id,
        "content": content,
        "score": score,
        "agent_id": agent_id,
        "scope": scope,
        "tags": tags or [],
        "importance_score": 0.5,
        "payload": payload,
    }


def _graph_node(
    record_id: str,
    agent_id: str = "agent1",
    scope: str = "per_agent",
    importance: float = 0.8,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "workspace_id": "ws1",
        "agent_id": agent_id,
        "scope": scope,
        "source_type": "chat",
        "importance_score": importance,
        "tags": tags or [],
    }


def _redis_record(
    record_id: str,
    content: str = "",
    tags: list[str] | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id="ws1",
        agent_id="agent1",
        scope=MemoryScope.SESSION,
        session_id="sess1",
        content=content,
        tags=tags or [],
    )


def _make_service(
    *,
    qdrant_hits: list[dict[str, Any]] | None = None,
    graph_hits: list[dict[str, Any]] | None = None,
    redis_records: list[MemoryRecord] | None = None,
    redis: Any = None,
    weights: MemorySearchWeights | None = None,
) -> tuple[MemorySearchService, MagicMock, Any]:
    qdrant = MagicMock()
    qdrant.search = AsyncMock(return_value=qdrant_hits or [])

    if redis is None and redis_records is not None:
        redis = MagicMock()
        redis.list = AsyncMock(return_value=redis_records)
        redis.get = AsyncMock(return_value=None)

    service = MemorySearchService(
        qdrant=qdrant,
        redis=redis,
        weights=weights or MemorySearchWeights(),
    )
    return service, qdrant, redis


# ---------------------------------------------------------------------------
# Parallel fan-out
# ---------------------------------------------------------------------------


class TestFanOut:
    async def test_all_legs_fire_when_agent_and_session_set(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(return_value=[_redis_record("r3", content="hello")])

        service, qdrant, _ = _make_service(
            qdrant_hits=[_qdrant_hit("r1", content="doc", score=0.9)],
            redis=redis_cache,
        )

        with patch(
            "metatron.memory.search.get_agent_memories",
            return_value=[_graph_node("r2")],
        ) as mock_graph:
            results = await service.hybrid_search(
                "ws1",
                "hello",
                agent_id="agent1",
                session_id="sess1",
            )

        qdrant.search.assert_awaited_once()
        mock_graph.assert_called_once()
        redis_cache.list.assert_awaited_once_with("ws1", "sess1")
        # r2 (graph) has no content → dropped; r1 + r3 remain
        ids = {r.record.id for r in results}
        assert ids == {"r1", "r3"}

    async def test_qdrant_only_when_no_agent_no_session(self) -> None:
        service, qdrant, _ = _make_service(
            qdrant_hits=[_qdrant_hit("r1", content="x", score=0.5)],
        )

        with patch("metatron.memory.search.get_agent_memories") as mock_graph:
            results = await service.hybrid_search("ws1", "q")

        qdrant.search.assert_awaited_once()
        mock_graph.assert_not_called()
        assert len(results) == 1
        assert results[0].record.id == "r1"


# ---------------------------------------------------------------------------
# Dedup + score blending
# ---------------------------------------------------------------------------


class TestDedup:
    async def test_qdrant_and_graph_merge_into_single_result(self) -> None:
        service, _, _ = _make_service(
            qdrant_hits=[_qdrant_hit("r1", content="c1", score=0.9)],
        )

        with patch(
            "metatron.memory.search.get_agent_memories",
            return_value=[_graph_node("r1", importance=0.7)],
        ):
            results = await service.hybrid_search("ws1", "q", agent_id="agent1")

        assert len(results) == 1
        r = results[0]
        assert r.record.id == "r1"
        assert r.dense_score > 0
        assert r.graph_score == pytest.approx(0.7)

    async def test_three_way_dedup_across_all_legs(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(return_value=[_redis_record("shared", content="hello there")])
        service, _, _ = _make_service(
            qdrant_hits=[_qdrant_hit("shared", content="hello there", score=0.9)],
            redis=redis_cache,
        )

        with patch(
            "metatron.memory.search.get_agent_memories",
            return_value=[_graph_node("shared", importance=0.6)],
        ):
            results = await service.hybrid_search(
                "ws1",
                "hello",
                agent_id="agent1",
                session_id="sess1",
            )

        assert len(results) == 1
        r = results[0]
        assert r.record.id == "shared"
        assert r.dense_score > 0
        assert r.graph_score == pytest.approx(0.6)
        # session boost applied → score > dense*1 + graph*0.6
        expected_with_boost = 0.6 * 1.0 + 0.3 * 0.6 + 0.1 * 1.0
        assert r.score == pytest.approx(expected_with_boost)


# ---------------------------------------------------------------------------
# Tags post-filter
# ---------------------------------------------------------------------------


class TestTagsFilter:
    async def test_drops_non_matching_tags(self) -> None:
        service, _, _ = _make_service(
            qdrant_hits=[
                _qdrant_hit("r1", content="a", score=0.9, tags=["alpha"]),
                _qdrant_hit("r2", content="b", score=0.8, tags=["beta"]),
            ],
        )

        results = await service.hybrid_search("ws1", "q", tags=["beta"])

        ids = {r.record.id for r in results}
        assert ids == {"r2"}


# ---------------------------------------------------------------------------
# Scope passed as .value
# ---------------------------------------------------------------------------


class TestScopePassthrough:
    async def test_scope_value_string_sent_to_qdrant_and_graph(self) -> None:
        service, qdrant, _ = _make_service(qdrant_hits=[])

        with patch(
            "metatron.memory.search.get_agent_memories",
            return_value=[],
        ) as mock_graph:
            await service.hybrid_search(
                "ws1",
                "q",
                agent_id="agent1",
                scope=MemoryScope.PER_AGENT,
            )

        qdrant.search.assert_awaited_once()
        _, kwargs = qdrant.search.call_args
        assert kwargs["scope"] == "per_agent"
        assert kwargs["agent_id"] == "agent1"

        graph_args = mock_graph.call_args.args
        # (workspace_id, agent_id, scope_value, pool)
        assert graph_args[2] == "per_agent"


# ---------------------------------------------------------------------------
# Leg failures
# ---------------------------------------------------------------------------


class TestLegFailures:
    async def test_graph_failure_does_not_break_search(self) -> None:
        service, _, _ = _make_service(
            qdrant_hits=[_qdrant_hit("r1", content="c", score=0.5)],
        )

        with patch(
            "metatron.memory.search.get_agent_memories",
            side_effect=RuntimeError("neo4j down"),
        ):
            results = await service.hybrid_search("ws1", "q", agent_id="agent1")

        assert len(results) == 1
        assert results[0].record.id == "r1"

    async def test_qdrant_failure_graph_and_redis_still_return(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(return_value=[_redis_record("r_sess", content="hello world")])
        qdrant = MagicMock()
        qdrant.search = AsyncMock(side_effect=RuntimeError("qdrant down"))
        service = MemorySearchService(qdrant=qdrant, redis=redis_cache)

        with patch(
            "metatron.memory.search.get_agent_memories",
            return_value=[_graph_node("r_sess", importance=0.8)],
        ):
            results = await service.hybrid_search(
                "ws1",
                "hello",
                agent_id="agent1",
                session_id="sess1",
            )

        ids = {r.record.id for r in results}
        assert ids == {"r_sess"}

    async def test_all_three_legs_fail_returns_empty(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(side_effect=RuntimeError("redis down"))
        qdrant = MagicMock()
        qdrant.search = AsyncMock(side_effect=RuntimeError("qdrant down"))
        service = MemorySearchService(qdrant=qdrant, redis=redis_cache)

        with patch(
            "metatron.memory.search.get_agent_memories",
            side_effect=RuntimeError("neo4j down"),
        ):
            results = await service.hybrid_search(
                "ws1",
                "hello",
                agent_id="agent1",
                session_id="sess1",
            )

        assert results == []


# ---------------------------------------------------------------------------
# Redis leg substring match
# ---------------------------------------------------------------------------


class TestRedisSubstring:
    async def test_redis_hit_when_substring_in_content(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(return_value=[_redis_record("r1", content="Hello World")])
        service, _, _ = _make_service(qdrant_hits=[], redis=redis_cache)

        results = await service.hybrid_search("ws1", "hello", session_id="sess1")

        assert len(results) == 1
        assert results[0].record.id == "r1"

    async def test_redis_miss_when_substring_absent(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(return_value=[_redis_record("r1", content="foobar")])
        service, _, _ = _make_service(qdrant_hits=[], redis=redis_cache)

        results = await service.hybrid_search("ws1", "hello", session_id="sess1")

        assert results == []


# ---------------------------------------------------------------------------
# Empty-content graph hits dropped
# ---------------------------------------------------------------------------


class TestGraphHydration:
    async def test_empty_content_graph_hit_dropped(self) -> None:
        service, _, _ = _make_service(qdrant_hits=[])

        with patch(
            "metatron.memory.search.get_agent_memories",
            return_value=[_graph_node("r_graph_only")],
        ):
            results = await service.hybrid_search("ws1", "q", agent_id="agent1")

        assert results == []

    async def test_graph_hit_hydrated_from_redis_cache(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(
            return_value=[_redis_record("r_g", content="hello from cache")]
        )
        service, _, _ = _make_service(qdrant_hits=[], redis=redis_cache)

        with patch(
            "metatron.memory.search.get_agent_memories",
            return_value=[_graph_node("r_g", importance=0.9)],
        ):
            results = await service.hybrid_search(
                "ws1",
                "hello",
                agent_id="agent1",
                session_id="sess1",
            )

        assert len(results) == 1
        r = results[0]
        assert r.record.id == "r_g"
        assert r.graph_score == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Weights affect ordering
# ---------------------------------------------------------------------------


class TestWeightsOrdering:
    async def test_session_boost_promotes_session_hit(self) -> None:
        redis_cache = MagicMock()
        redis_cache.list = AsyncMock(return_value=[_redis_record("r_sess", content="hello world")])
        # Session weight dominates
        service, _, _ = _make_service(
            qdrant_hits=[_qdrant_hit("r_qd", content="other", score=0.9)],
            redis=redis_cache,
            weights=MemorySearchWeights(dense=0.05, graph=0.05, session=0.9),
        )

        results = await service.hybrid_search("ws1", "hello", session_id="sess1")

        assert results[0].record.id == "r_sess"


# ---------------------------------------------------------------------------
# top_k truncation + ranking
# ---------------------------------------------------------------------------


class TestRankingAndTruncation:
    async def test_returns_at_most_top_k_sorted_with_rank(self) -> None:
        hits = [_qdrant_hit(f"r{i}", content=f"c{i}", score=float(10 - i)) for i in range(6)]
        service, _, _ = _make_service(qdrant_hits=hits)

        results = await service.hybrid_search("ws1", "q", top_k=3)

        assert len(results) == 3
        assert [r.rank for r in results] == [1, 2, 3]
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
        # Highest raw score should rank first
        assert results[0].record.id == "r0"


# ---------------------------------------------------------------------------
# Fire-and-forget touch hook (MTRNIX-277)
# ---------------------------------------------------------------------------


def _make_service_with_pg(
    *,
    qdrant_hits: list[dict[str, Any]] | None = None,
    pg_store: Any = None,
) -> tuple[MemorySearchService, Any, Any]:
    qdrant = MagicMock()
    qdrant.search = AsyncMock(return_value=qdrant_hits or [])
    service = MemorySearchService(
        qdrant=qdrant,
        weights=MemorySearchWeights(),
        pg_store=pg_store,
    )
    return service, qdrant, pg_store


class TestTouchHook:
    async def test_touch_called_with_ranked_ids(self) -> None:
        """After search, bulk_touch_last_accessed is called for all ranked ids."""
        pg_store = AsyncMock()
        pg_store.bulk_touch_last_accessed = AsyncMock(return_value=2)

        service, _, _ = _make_service_with_pg(
            qdrant_hits=[
                _qdrant_hit("r1", content="first", score=0.9),
                _qdrant_hit("r2", content="second", score=0.5),
            ],
            pg_store=pg_store,
        )

        results = await service.hybrid_search(
            "ws1",
            "hello",
            agent_id="a1",
        )
        assert len(results) == 2

        # Let pending tasks run.
        await asyncio.sleep(0)
        pg_store.bulk_touch_last_accessed.assert_awaited_once()
        _, called_agent_id, called_ids = pg_store.bulk_touch_last_accessed.call_args[0]
        assert called_agent_id == "a1"
        assert set(called_ids) == {"r1", "r2"}

    async def test_touch_failure_does_not_propagate(self) -> None:
        """Errors in _safe_bulk_touch are swallowed — search still succeeds."""
        pg_store = AsyncMock()
        pg_store.bulk_touch_last_accessed = AsyncMock(side_effect=Exception("DB exploded"))

        service, _, _ = _make_service_with_pg(
            qdrant_hits=[_qdrant_hit("r1", content="x", score=1.0)],
            pg_store=pg_store,
        )

        # Must not raise.
        results = await service.hybrid_search("ws1", "hi", agent_id="a1")
        assert len(results) == 1
        await asyncio.sleep(0)  # let the task complete

    async def test_no_touch_when_agent_id_none(self) -> None:
        """With no agent_id, no task is scheduled."""
        pg_store = AsyncMock()
        pg_store.bulk_touch_last_accessed = AsyncMock()

        service, _, _ = _make_service_with_pg(
            qdrant_hits=[_qdrant_hit("r1", content="x", score=1.0)],
            pg_store=pg_store,
        )

        await service.hybrid_search("ws1", "query")  # agent_id defaults to None
        await asyncio.sleep(0)
        pg_store.bulk_touch_last_accessed.assert_not_awaited()

    async def test_no_touch_when_pg_store_none(self) -> None:
        """With no pg_store, no task is scheduled."""
        qdrant = MagicMock()
        qdrant.search = AsyncMock(return_value=[_qdrant_hit("r1", content="x", score=1.0)])
        service = MemorySearchService(qdrant=qdrant, weights=MemorySearchWeights())

        # Should not raise.
        results = await service.hybrid_search("ws1", "hi", agent_id="a1")
        assert len(results) == 1

    async def test_no_touch_when_empty_results(self) -> None:
        """With empty ranked results, no task is scheduled."""
        pg_store = AsyncMock()
        pg_store.bulk_touch_last_accessed = AsyncMock()

        service, _, _ = _make_service_with_pg(qdrant_hits=[], pg_store=pg_store)

        await service.hybrid_search("ws1", "hi", agent_id="a1")
        await asyncio.sleep(0)
        pg_store.bulk_touch_last_accessed.assert_not_awaited()
