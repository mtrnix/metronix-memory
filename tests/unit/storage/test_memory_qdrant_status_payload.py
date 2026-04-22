"""Unit tests for MemoryQdrantStore status payload + exclude filter (MTRNIX-314).

Covers:
* ``upsert`` writes ``status`` into the point payload.
* ``search(status_exclude=...)`` attaches a ``MatchAny`` exclude filter.
* ``search`` with no status_exclude leaves filter shape unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from qdrant_client.models import FieldCondition, Filter, MatchAny

from metatron.core.models import LifecycleStatus, MemoryRecord, MemoryScope
from metatron.storage.memory_qdrant import MemoryQdrantStore


def _make_record(status: LifecycleStatus = LifecycleStatus.ACTIVE) -> MemoryRecord:
    return MemoryRecord(
        id="mem001",
        workspace_id="ws1",
        agent_id="agent1",
        scope=MemoryScope.PER_AGENT,
        source_type="conversation",
        content="user prefers dark mode",
        tags=["preference"],
        importance_score=0.8,
        ttl_expires_at=None,
        content_hash="abc123",
        session_id=None,
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=status,
    )


async def _make_store_patched() -> MemoryQdrantStore:
    with patch("metatron.storage.memory_qdrant.AsyncQdrantClient") as client_cls:
        client_cls.return_value = AsyncMock()
        store = MemoryQdrantStore(workspace_id="ws1")
    return store


class TestUpsertStatusPayload:
    async def test_upsert_includes_status_in_payload(self) -> None:
        store = await _make_store_patched()
        store._collection_ensured = True
        store._client.upsert = AsyncMock()

        with (
            patch(
                "metatron.storage.memory_qdrant.get_cached_embedding",
                return_value=[0.1] * 768,
            ),
            patch(
                "metatron.storage.memory_qdrant._compute_doc_sparse",
                return_value=([1], [0.5]),
            ),
        ):
            record = _make_record(status=LifecycleStatus.STALE)
            await store.upsert(record)

        call = store._client.upsert.await_args
        assert call is not None
        points = call.kwargs["points"]
        assert len(points) == 1
        payload = points[0].payload
        assert payload["status"] == "stale"

    async def test_upsert_default_active_status(self) -> None:
        store = await _make_store_patched()
        store._collection_ensured = True
        store._client.upsert = AsyncMock()

        with (
            patch(
                "metatron.storage.memory_qdrant.get_cached_embedding",
                return_value=[0.1] * 768,
            ),
            patch(
                "metatron.storage.memory_qdrant._compute_doc_sparse",
                return_value=([1], [0.5]),
            ),
        ):
            await store.upsert(_make_record())

        call = store._client.upsert.await_args
        payload = call.kwargs["points"][0].payload
        assert payload["status"] == "active"


class TestSearchStatusExclude:
    async def test_search_with_status_exclude_builds_must_not(self) -> None:
        store = await _make_store_patched()
        store._collection_ensured = True
        store._client.query_points = AsyncMock(return_value=SimpleNamespace(points=[]))

        with (
            patch(
                "metatron.storage.memory_qdrant.get_cached_embedding",
                return_value=[0.1] * 768,
            ),
            patch(
                "metatron.storage.memory_qdrant._compute_query_sparse",
                return_value=([1], [0.5]),
            ),
        ):
            await store.search(
                "dark mode",
                agent_id="agent1",
                status_exclude=["archived", "superseded"],
            )

        call = store._client.query_points.await_args
        qfilter: Filter = call.kwargs["query_filter"]
        assert qfilter is not None
        assert qfilter.must is not None
        # must clause should carry the existing agent_id condition.
        must_keys = [c.key for c in qfilter.must if isinstance(c, FieldCondition)]
        assert "agent_id" in must_keys
        # must_not clause should carry the status exclude.
        assert qfilter.must_not is not None
        exclude_cond = next((c for c in qfilter.must_not if isinstance(c, FieldCondition)), None)
        assert exclude_cond is not None
        assert exclude_cond.key == "status"
        assert isinstance(exclude_cond.match, MatchAny)
        assert set(exclude_cond.match.any) == {"archived", "superseded"}

    async def test_search_without_status_exclude_has_no_must_not(self) -> None:
        store = await _make_store_patched()
        store._collection_ensured = True
        store._client.query_points = AsyncMock(return_value=SimpleNamespace(points=[]))

        with (
            patch(
                "metatron.storage.memory_qdrant.get_cached_embedding",
                return_value=[0.1] * 768,
            ),
            patch(
                "metatron.storage.memory_qdrant._compute_query_sparse",
                return_value=([1], [0.5]),
            ),
        ):
            await store.search("dark mode", agent_id="agent1")

        call = store._client.query_points.await_args
        qfilter: Filter | None = call.kwargs["query_filter"]
        # must clause exists (agent_id); must_not either None or empty list.
        assert qfilter is not None
        assert not qfilter.must_not

    async def test_search_empty_status_exclude_is_noop(self) -> None:
        store = await _make_store_patched()
        store._collection_ensured = True
        store._client.query_points = AsyncMock(return_value=SimpleNamespace(points=[]))

        with (
            patch(
                "metatron.storage.memory_qdrant.get_cached_embedding",
                return_value=[0.1] * 768,
            ),
            patch(
                "metatron.storage.memory_qdrant._compute_query_sparse",
                return_value=([1], [0.5]),
            ),
        ):
            await store.search("query", status_exclude=[])

        call = store._client.query_points.await_args
        qfilter = call.kwargs["query_filter"]
        # No agent/scope + empty exclude → no filter at all.
        if qfilter is not None:
            assert not qfilter.must_not

    async def test_search_status_exclude_alone_builds_filter(self) -> None:
        store = await _make_store_patched()
        store._collection_ensured = True
        store._client.query_points = AsyncMock(return_value=SimpleNamespace(points=[]))

        with (
            patch(
                "metatron.storage.memory_qdrant.get_cached_embedding",
                return_value=[0.1] * 768,
            ),
            patch(
                "metatron.storage.memory_qdrant._compute_query_sparse",
                return_value=([1], [0.5]),
            ),
        ):
            await store.search("query", status_exclude=["archived"])

        call = store._client.query_points.await_args
        qfilter: Filter = call.kwargs["query_filter"]
        assert qfilter is not None
        assert qfilter.must_not is not None
        exclude_cond = next((c for c in qfilter.must_not if isinstance(c, FieldCondition)), None)
        assert exclude_cond is not None
        assert exclude_cond.key == "status"
