"""Tests for MemoryQdrantStore (WS1 Stage 2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.storage.memory_qdrant import MemoryQdrantStore


def _mock_collections(*names: str):
    """Return a mock get_collections response."""
    cols = [SimpleNamespace(name=n) for n in names]
    return SimpleNamespace(collections=cols)


def _make_store(workspace_id: str = "ws1") -> MemoryQdrantStore:
    """Create a MemoryQdrantStore with a mocked Qdrant client."""
    store = MemoryQdrantStore(workspace_id=workspace_id)
    store._client = AsyncMock()
    return store


def _sample_record(**overrides) -> MemoryRecord:
    defaults = {
        "id": "mem001",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "source_type": "conversation",
        "content": "user prefers dark mode",
        "tags": ["preference"],
        "importance_score": 0.8,
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


# ---------------------------------------------------------------------------
# _ensure_collection
# ---------------------------------------------------------------------------


class TestEnsureCollection:
    async def test_creates_collection_on_first_call(self) -> None:
        store = _make_store()
        store._client.get_collections.return_value = _mock_collections()

        await store._ensure_collection()

        store._client.create_collection.assert_awaited_once()
        # Should create payload indexes for agent_id and scope
        assert store._client.create_payload_index.await_count == 2
        assert store._collection_ensured is True

    async def test_skips_when_exists(self) -> None:
        store = _make_store()
        store._client.get_collections.return_value = _mock_collections(
            "mem_agent_memory_ws1",
        )

        await store._ensure_collection()

        store._client.create_collection.assert_not_awaited()
        assert store._collection_ensured is True

    async def test_skips_on_second_call(self) -> None:
        store = _make_store()
        store._collection_ensured = True

        await store._ensure_collection()

        store._client.get_collections.assert_not_awaited()

    async def test_collection_name_includes_workspace(self) -> None:
        store = _make_store(workspace_id="myws")
        assert store._collection == "mem_agent_memory_myws"


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


class TestUpsert:
    @patch(
        "metatron.storage.memory_qdrant._compute_doc_sparse",
        return_value=([1, 2], [0.5, 0.3]),
    )
    @patch(
        "metatron.storage.memory_qdrant.get_cached_embedding",
        return_value=[0.1] * 768,
    )
    async def test_upserts_record_with_vectors(self, mock_embed, mock_sparse) -> None:
        store = _make_store()
        store._collection_ensured = True
        record = _sample_record()

        await store.upsert(record)

        store._client.upsert.assert_awaited_once()
        points = store._client.upsert.call_args.kwargs["points"]
        assert len(points) == 1
        assert points[0].id == "mem001"

        payload = points[0].payload
        assert payload["content"] == "user prefers dark mode"
        assert payload["agent_id"] == "agent1"
        assert payload["scope"] == "per_agent"
        assert payload["importance_score"] == 0.8
        assert payload["tags"] == ["preference"]
        assert payload["record_id"] == "mem001"

    @patch(
        "metatron.storage.memory_qdrant._compute_doc_sparse",
        return_value=([1, 2], [0.5, 0.3]),
    )
    @patch(
        "metatron.storage.memory_qdrant.get_cached_embedding",
        return_value=[0.1] * 768,
    )
    async def test_uses_record_id_as_point_id(self, mock_embed, mock_sparse) -> None:
        store = _make_store()
        store._collection_ensured = True
        record = _sample_record(id="custom-id-123")

        await store.upsert(record)

        points = store._client.upsert.call_args.kwargs["points"]
        assert points[0].id == "custom-id-123"

    @patch(
        "metatron.storage.memory_qdrant._compute_doc_sparse",
        return_value=([1, 2], [0.5, 0.3]),
    )
    @patch(
        "metatron.storage.memory_qdrant.get_cached_embedding",
        return_value=[0.1] * 768,
    )
    async def test_includes_both_dense_and_sparse_vectors(
        self,
        mock_embed,
        mock_sparse,
    ) -> None:
        store = _make_store()
        store._collection_ensured = True
        record = _sample_record()

        await store.upsert(record)

        point = store._client.upsert.call_args.kwargs["points"][0]
        assert "dense" in point.vector
        assert "bm25" in point.vector
        assert len(point.vector["dense"]) == 768


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    @patch(
        "metatron.storage.memory_qdrant._compute_query_sparse",
        return_value=([1, 2], [0.5, 0.3]),
    )
    @patch(
        "metatron.storage.memory_qdrant.get_cached_embedding",
        return_value=[0.1] * 768,
    )
    async def test_hybrid_search_returns_results(
        self,
        mock_embed,
        mock_sparse,
    ) -> None:
        store = _make_store()
        store._collection_ensured = True
        mock_point = SimpleNamespace(
            id="mem001",
            payload={
                "content": "dark mode",
                "record_id": "mem001",
                "agent_id": "agent1",
                "scope": "per_agent",
                "importance_score": 0.8,
                "tags": ["preference"],
            },
            score=0.95,
        )
        store._client.query_points.return_value = SimpleNamespace(
            points=[mock_point],
        )

        results = await store.search("dark mode preference", top_k=5)

        assert len(results) == 1
        assert results[0]["record_id"] == "mem001"
        assert results[0]["score"] == 0.95
        assert results[0]["content"] == "dark mode"

    @patch(
        "metatron.storage.memory_qdrant._compute_query_sparse",
        return_value=([1, 2], [0.5, 0.3]),
    )
    @patch(
        "metatron.storage.memory_qdrant.get_cached_embedding",
        return_value=[0.1] * 768,
    )
    async def test_search_with_agent_filter(self, mock_embed, mock_sparse) -> None:
        store = _make_store()
        store._collection_ensured = True
        store._client.query_points.return_value = SimpleNamespace(points=[])

        await store.search("query", agent_id="agent1")

        call_kwargs = store._client.query_points.call_args.kwargs
        prefetch_list = call_kwargs["prefetch"]
        # Both prefetch queries should have the agent_id filter
        assert prefetch_list[0].filter is not None
        assert prefetch_list[1].filter is not None

    @patch(
        "metatron.storage.memory_qdrant._compute_query_sparse",
        return_value=([1, 2], [0.5, 0.3]),
    )
    @patch(
        "metatron.storage.memory_qdrant.get_cached_embedding",
        return_value=[0.1] * 768,
    )
    async def test_search_without_filters(self, mock_embed, mock_sparse) -> None:
        store = _make_store()
        store._collection_ensured = True
        store._client.query_points.return_value = SimpleNamespace(points=[])

        await store.search("query")

        call_kwargs = store._client.query_points.call_args.kwargs
        prefetch_list = call_kwargs["prefetch"]
        # No filter when no agent_id/scope provided
        assert prefetch_list[0].filter is None

    @patch(
        "metatron.storage.memory_qdrant._compute_query_sparse",
        return_value=([1, 2], [0.5, 0.3]),
    )
    @patch(
        "metatron.storage.memory_qdrant.get_cached_embedding",
        return_value=[0.1] * 768,
    )
    async def test_search_returns_empty_on_no_results(
        self,
        mock_embed,
        mock_sparse,
    ) -> None:
        store = _make_store()
        store._collection_ensured = True
        store._client.query_points.return_value = SimpleNamespace(points=[])

        results = await store.search("nothing matches")

        assert results == []


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_by_record_id(self) -> None:
        store = _make_store()
        store._collection_ensured = True
        store._client.retrieve.return_value = [
            SimpleNamespace(id="mem001", payload={"record_id": "mem001"}),
        ]

        result = await store.delete("mem001")

        assert result is True
        store._client.delete.assert_awaited_once()
        call_kwargs = store._client.delete.call_args.kwargs
        assert call_kwargs["points_selector"] == ["mem001"]

    async def test_delete_missing_returns_false(self) -> None:
        store = _make_store()
        store._collection_ensured = True
        store._client.retrieve.return_value = []

        result = await store.delete("missing")

        assert result is False
        store._client.delete.assert_not_awaited()

    async def test_delete_by_agent(self) -> None:
        store = _make_store()
        store._collection_ensured = True

        await store.delete_by_agent("agent1")

        store._client.delete.assert_awaited_once()
        call_kwargs = store._client.delete.call_args.kwargs
        # Should use a Filter, not a list of IDs
        selector = call_kwargs["points_selector"]
        assert hasattr(selector, "must")  # It's a Filter object
