"""Tests for AsyncQdrantVectorStore."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from metatron.storage.qdrant import (
    AsyncQdrantVectorStore,
    clear_store_cache,
    get_async_hybrid_store,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_point(point_id="p1", payload=None, score=0.9):
    """Create a fake Qdrant point object."""
    return SimpleNamespace(
        id=point_id,
        payload=payload or {"data": "hello", "title": "T", "type": "doc"},
        score=score,
    )


def _mock_collections(*names: str):
    """Return a mock get_collections response with given collection names."""
    cols = [SimpleNamespace(name=n) for n in names]
    return SimpleNamespace(collections=cols)


# ---------------------------------------------------------------------------
# _ensure_collection
# ---------------------------------------------------------------------------

class TestEnsureCollection:
    async def test_creates_collection_on_first_call(self):
        store = AsyncQdrantVectorStore(workspace_id="ws1")
        store.client = AsyncMock()
        store.client.get_collections.return_value = _mock_collections()

        await store._ensure_collection()

        store.client.create_collection.assert_awaited_once()
        store.client.create_payload_index.assert_awaited_once()
        assert store._collection_ensured is True

    async def test_skips_creation_when_collection_exists(self):
        store = AsyncQdrantVectorStore(workspace_id="ws1")
        store.client = AsyncMock()
        store.client.get_collections.return_value = _mock_collections(
            store.collection_name
        )

        await store._ensure_collection()

        store.client.create_collection.assert_not_awaited()
        assert store._collection_ensured is True

    async def test_skips_entirely_on_second_call(self):
        store = AsyncQdrantVectorStore(workspace_id="ws1")
        store.client = AsyncMock()
        store._collection_ensured = True

        await store._ensure_collection()

        store.client.get_collections.assert_not_awaited()


# ---------------------------------------------------------------------------
# add_document
# ---------------------------------------------------------------------------

class TestAddDocument:
    @patch("metatron.storage.qdrant.get_cached_embedding_split")
    @patch("metatron.storage.qdrant.compute_bm25_sparse_vector")
    async def test_add_document_calls_upsert(self, mock_bm25, mock_embed):
        mock_embed.return_value = [("chunk text", [0.1] * 768)]
        mock_bm25.return_value = ([1, 2], [0.5, 0.6])

        store = AsyncQdrantVectorStore(workspace_id="ws1")
        store.client = AsyncMock()
        store._collection_ensured = True

        ids = await store.add_document("some text", metadata={"title": "T"})

        assert len(ids) == 1
        store.client.upsert.assert_awaited_once()
        call_kwargs = store.client.upsert.call_args
        points = call_kwargs.kwargs.get("points") or call_kwargs[1].get("points")
        assert len(points) == 1
        assert points[0].payload["workspace_id"] == "ws1"


# ---------------------------------------------------------------------------
# hybrid_search
# ---------------------------------------------------------------------------

class TestHybridSearch:
    @patch("metatron.storage.qdrant.compute_query_sparse_vector")
    @patch("metatron.storage.qdrant.get_cached_embedding")
    async def test_hybrid_search_returns_results(self, mock_embed, mock_sparse):
        mock_embed.return_value = [0.1] * 768
        mock_sparse.return_value = ([1], [0.5])

        store = AsyncQdrantVectorStore(workspace_id="ws1")
        store.client = AsyncMock()
        store._collection_ensured = True
        store.client.query_points.return_value = SimpleNamespace(
            points=[_make_point()]
        )

        results = await store.hybrid_search("test query", limit=5)

        assert len(results) == 1
        assert results[0]["data"] == "hello"
        store.client.query_points.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_async_hybrid_store caching
# ---------------------------------------------------------------------------

class TestAsyncFactory:
    @patch("metatron.storage.qdrant.AsyncQdrantClient")
    async def test_caching_returns_same_instance(self, mock_client_cls):
        clear_store_cache()

        store1 = await get_async_hybrid_store(
            workspace_id="ws1", host="localhost", port=6333
        )
        store2 = await get_async_hybrid_store(
            workspace_id="ws1", host="localhost", port=6333
        )

        assert store1 is store2

    @patch("metatron.storage.qdrant.AsyncQdrantClient")
    async def test_different_workspaces_get_different_stores(self, mock_client_cls):
        clear_store_cache()

        store1 = await get_async_hybrid_store(
            workspace_id="ws1", host="localhost", port=6333
        )
        store2 = await get_async_hybrid_store(
            workspace_id="ws2", host="localhost", port=6333
        )

        assert store1 is not store2


# ---------------------------------------------------------------------------
# clear_store_cache
# ---------------------------------------------------------------------------

class TestClearStoreCache:
    @patch("metatron.storage.qdrant.AsyncQdrantClient")
    @patch("metatron.storage.qdrant.QdrantClient")
    async def test_clears_both_caches(self, mock_sync_cls, mock_async_cls):
        clear_store_cache()

        # Populate async cache
        await get_async_hybrid_store(
            workspace_id="ws1", host="localhost", port=6333
        )

        # Import to check sync cache dict directly
        from metatron.storage import qdrant

        assert len(qdrant._async_hybrid_stores) == 1

        clear_store_cache()

        assert len(qdrant._async_hybrid_stores) == 0
        assert len(qdrant._hybrid_stores) == 0
