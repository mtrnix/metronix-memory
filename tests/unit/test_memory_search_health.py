"""Search failures must remain distinguishable from healthy empty results."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.core.models import MemoryRecord
from metronix.memory.search import MemorySearchService, MemorySearchWeights
from metronix.memory.service import MemoryService


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch):
    qdrant = MagicMock(search=AsyncMock(return_value=[]))
    redis = MagicMock(list=AsyncMock(return_value=[]))
    graph = MagicMock(return_value=[])
    pg = MagicMock(bulk_touch_last_accessed=AsyncMock(), get_many_statuses=AsyncMock())
    monkeypatch.setattr("metronix.memory.search.get_agent_memories", graph)
    search = MemorySearchService(qdrant, redis, weights=MemorySearchWeights(), pg_store=pg)
    return search, qdrant, redis, graph, pg


def hit(record_id: str = "known-hit") -> dict[str, Any]:
    return {
        "record_id": record_id,
        "content": "known content",
        "score": 0.8,
        "payload": {
            "record_id": record_id,
            "content": "known content",
            "agent_id": "agent1",
            "workspace_id": "ws1",
        },
    }


async def test_qdrant_outage_without_session_reports_hydration_loss(stores):
    search, qdrant, _, graph, _ = stores
    qdrant.search.side_effect = RuntimeError("private-host fake-password")
    graph.return_value = [{"id": "known-hit"}]
    outcome = await search.hybrid_search_detailed("ws1", "known", agent_id="agent1")
    assert outcome.results == []
    assert outcome.partial is True
    assert asdict(outcome.legs.qdrant) == {
        "status": "failed",
        "reason": "backend_error",
        "retryable": None,
    }
    assert outcome.legs.graph.status == "ok"
    assert asdict(outcome.legs.graph.hydration) == {
        "status": "unavailable",
        "retrieved": 1,
        "resolved": 0,
        "unavailable": 1,
        "invalid": 0,
    }
    assert outcome.legs.session.status == "skipped"
    assert "private-host" not in str(asdict(outcome))
    assert "fake-password" not in str(asdict(outcome))


async def test_outage_preserves_session_backed_graph_hit(stores):
    search, qdrant, redis, graph, _ = stores
    qdrant.search.side_effect = OSError("offline")
    graph.return_value = [{"id": "known-hit"}]
    redis.list.return_value = [
        MemoryRecord(
            id="known-hit", workspace_id="ws1", agent_id="agent1", content="known content"
        )
    ]
    outcome = await search.hybrid_search_detailed(
        "ws1",
        "known",
        agent_id="agent1",
        session_id="sess1",
    )
    assert [r.record.id for r in outcome.results] == ["known-hit"]
    assert outcome.partial is True
    assert outcome.legs.graph.hydration.resolved == 1
    assert outcome.legs.graph.hydration.status == "ok"


@pytest.mark.parametrize("has_hit", [False, True])
async def test_healthy_results_and_empty_are_complete(stores, has_hit):
    search, qdrant, _, _, _ = stores
    qdrant.search.return_value = [hit()] if has_hit else []
    outcome = await search.hybrid_search_detailed("ws1", "known", agent_id="agent1")
    assert len(outcome.results) == int(has_hit)
    assert outcome.partial is False
    assert outcome.legs.qdrant.status == outcome.legs.graph.status == "ok"
    assert outcome.legs.graph.hydration.status == "ok"
    assert outcome.legs.session.status == "skipped"


async def test_absent_optional_legs_are_skipped(stores):
    search, qdrant, _, _, _ = stores
    for service, session_id in [(search, None), (MemorySearchService(qdrant), "sess1")]:
        outcome = await service.hybrid_search_detailed("ws1", "known", session_id=session_id)
        assert outcome.partial is False
        assert outcome.legs.graph.status == outcome.legs.session.status == "skipped"
        assert outcome.legs.graph.hydration.status == "not_attempted"


@pytest.mark.parametrize("failed", ["qdrant", "graph", "session", "all"])
async def test_each_leg_failure_is_reported(stores, failed):
    search, qdrant, redis, graph, _ = stores
    for name, call in [("qdrant", qdrant.search), ("graph", graph), ("session", redis.list)]:
        if failed in (name, "all"):
            call.side_effect = OSError("unavailable")
    outcome = await search.hybrid_search_detailed(
        "ws1", "known", agent_id="agent1", session_id="s"
    )
    assert outcome.results == []
    assert outcome.partial is True
    for name in ("qdrant", "graph", "session"):
        assert getattr(outcome.legs, name).status == (
            "failed" if failed in (name, "all") else "ok"
        )
    if failed in ("graph", "all"):
        assert outcome.legs.graph.hydration.status == "not_attempted"


async def test_timeout_is_explicitly_retryable(stores):
    search, qdrant, _, _, _ = stores
    qdrant.search.side_effect = TimeoutError("backend details")
    outcome = await search.hybrid_search_detailed("ws1", "known")
    assert outcome.legs.qdrant.reason == "timeout"
    assert outcome.legs.qdrant.retryable is True


async def test_mixed_duplicate_and_invalid_graph_hydration(stores):
    search, qdrant, _, graph, _ = stores
    qdrant.search.return_value = [hit()]
    graph.return_value = [{"id": "known-hit"}, {"id": "known-hit"}, {"id": "missing"}, {}]
    outcome = await search.hybrid_search_detailed("ws1", "known", agent_id="agent1")
    assert len(outcome.results) == 1
    assert outcome.partial is False
    assert asdict(outcome.legs.graph.hydration) == {
        "status": "partial",
        "retrieved": 4,
        "resolved": 2,
        "unavailable": 1,
        "invalid": 1,
    }


@pytest.mark.parametrize("tags,top_k,count", [(["absent"], 5, 0), (None, 1, 1)])
async def test_filters_and_top_k_do_not_count_as_hydration_loss(stores, tags, top_k, count):
    search, qdrant, _, graph, _ = stores
    qdrant.search.return_value = [hit("a"), hit("b")]
    graph.return_value = [{"id": "a"}, {"id": "b"}]
    outcome = await search.hybrid_search_detailed(
        "ws1",
        "known",
        agent_id="agent1",
        tags=tags,
        top_k=top_k,
    )
    assert len(outcome.results) == count
    assert outcome.legs.graph.hydration.resolved == 2
    assert outcome.partial is False


async def test_cancellation_propagates(stores):
    search, qdrant, _, _, _ = stores
    qdrant.search.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await search.hybrid_search_detailed("ws1", "known")


async def test_concurrent_requests_keep_health_local(stores):
    search, qdrant, _, _, _ = stores
    started = asyncio.Event()
    release = asyncio.Event()

    async def retrieve(query, **kwargs):
        if query == "failing":
            started.set()
            await release.wait()
            raise TimeoutError()
        await started.wait()
        release.set()
        return [hit()]

    qdrant.search.side_effect = retrieve
    failed, healthy = await asyncio.gather(
        search.hybrid_search_detailed("ws1", "failing"),
        search.hybrid_search_detailed("ws1", "healthy"),
    )
    assert failed.partial is True
    assert healthy.partial is False
    assert healthy.legs.qdrant.status == "ok"
    assert len(healthy.results) == 1


async def test_processing_errors_propagate(stores):
    search, qdrant, _, _, _ = stores
    qdrant.search.return_value = [{"score": "malformed"}]
    with pytest.raises(ValueError):
        await search.hybrid_search_detailed("ws1", "known")


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
async def test_blank_query_never_reaches_backends(stores, query):
    search, qdrant, redis, graph, _ = stores
    with pytest.raises(ValueError, match="query"):
        await search.hybrid_search_detailed("ws1", query, agent_id="agent1", session_id="s")
    qdrant.search.assert_not_called()
    redis.list.assert_not_called()
    graph.assert_not_called()


@pytest.mark.parametrize("detailed", [False, True])
async def test_service_preserves_workspace_and_configuration_errors(stores, detailed):
    _, qdrant, redis, _, pg = stores
    service = MemoryService(redis, qdrant, pg, workspace_id="ws1")
    method = service.search_detailed if detailed else service.search
    with pytest.raises(ValueError, match="workspace_id mismatch"):
        await method("other", "known")
    with pytest.raises(RuntimeError, match="search not configured"):
        await method("ws1", "known")


@pytest.mark.parametrize("method_name", ["hybrid_search", "search", "search_detailed"])
async def test_list_compatibility_and_single_execution(stores, method_name):
    search, qdrant, redis, _, pg = stores
    qdrant.search.return_value = [hit()]
    service = MemoryService(redis, qdrant, pg, workspace_id="ws1", search=search)
    owner = search if method_name == "hybrid_search" else service
    result = await getattr(owner, method_name)("ws1", " known ", agent_id="agent1")
    if method_name == "search_detailed":
        result = result.results
    assert isinstance(result, list)
    assert [r.record.id for r in result] == ["known-hit"]
    await asyncio.sleep(0)
    qdrant.search.assert_awaited_once()
    assert qdrant.search.await_args.args[0] == " known "
    pg.bulk_touch_last_accessed.assert_awaited_once_with("ws1", "agent1", ["known-hit"])
