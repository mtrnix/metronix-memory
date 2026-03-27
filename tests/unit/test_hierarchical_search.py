"""Tests for hierarchical chunking in the search/retrieval pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.retrieval.search import _prepend_root_context


def _make_result(
    chunk_type: str = "child",
    parent_id: str = "root_001",
    chunk_id: str = "child_001",
    data: str = "Child chunk content.",
) -> dict:
    return {
        "id": chunk_id,
        "score": 0.9,
        "memory": data,
        "data": data,
        "title": "Test Doc",
        "type": "confluence",
        "url": "",
        "date": "",
        "doc_label": "doc1",
        "workspace_id": "ws_test",
        "source_role": "knowledge_base",
        "payload": {
            "chunk_type": chunk_type,
            "parent_id": parent_id,
            "chunk_id": chunk_id,
            "data": data,
            "memory": data,
        },
    }


def _make_root_result(
    chunk_id: str = "root_001",
    data: str = "Root overview content.",
) -> dict:
    return {
        "id": chunk_id,
        "score": 1.0,
        "memory": data,
        "data": data,
        "title": "Test Doc",
        "type": "confluence",
        "url": "",
        "date": "",
        "doc_label": "doc1",
        "workspace_id": "ws_test",
        "source_role": "knowledge_base",
        "payload": {
            "chunk_type": "root",
            "parent_id": "",
            "chunk_id": chunk_id,
            "data": data,
            "memory": data,
        },
    }


class TestPrependRootContext:
    """_prepend_root_context fetches and prepends root chunks."""

    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_child_chunks_get_root_prepended(self, mock_store_fn) -> None:
        mock_store = MagicMock()
        mock_store.fetch_by_chunk_ids.return_value = [
            _make_root_result(),
        ]
        mock_store_fn.return_value = mock_store

        results = [_make_result()]
        updated = _prepend_root_context(results, "ws_test")

        assert len(updated) == 1
        assert "[ROOT CONTEXT]" in updated[0]["data"]
        assert "Root overview content." in updated[0]["data"]
        assert "Child chunk content." in updated[0]["data"]

    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_standalone_chunks_unchanged(self, mock_store_fn) -> None:
        results = [_make_result(chunk_type="standalone", parent_id="")]
        updated = _prepend_root_context(results, "ws_test")

        # No fetch should happen — no child chunks
        mock_store_fn.assert_not_called()
        assert updated[0]["data"] == "Child chunk content."

    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_deduplicates_root_fetches(self, mock_store_fn) -> None:
        """Multiple children with same parent_id trigger only one fetch."""
        mock_store = MagicMock()
        mock_store.fetch_by_chunk_ids.return_value = [
            _make_root_result(),
        ]
        mock_store_fn.return_value = mock_store

        results = [
            _make_result(chunk_id="child_001"),
            _make_result(chunk_id="child_002"),
        ]
        _prepend_root_context(results, "ws_test")

        # fetch_by_chunk_ids called once with single parent_id
        mock_store.fetch_by_chunk_ids.assert_called_once()
        call_args = mock_store.fetch_by_chunk_ids.call_args[0]
        assert call_args[0] == ["root_001"]

    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_graceful_degradation_on_fetch_failure(
        self, mock_store_fn,
    ) -> None:
        mock_store_fn.side_effect = Exception("Qdrant unavailable")

        results = [_make_result()]
        original_data = results[0]["data"]
        updated = _prepend_root_context(results, "ws_test")

        # Results should be returned unchanged
        assert len(updated) == 1
        assert updated[0]["data"] == original_data

    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_missing_root_leaves_child_unchanged(self, mock_store_fn) -> None:
        """When root chunk not found in Qdrant, child is not modified."""
        mock_store = MagicMock()
        mock_store.fetch_by_chunk_ids.return_value = []  # root not found
        mock_store_fn.return_value = mock_store

        results = [_make_result()]
        original_data = results[0]["data"]
        updated = _prepend_root_context(results, "ws_test")

        assert updated[0]["data"] == original_data
