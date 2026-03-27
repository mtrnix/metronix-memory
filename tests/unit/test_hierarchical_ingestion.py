"""Tests for hierarchical chunking in the ingestion pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.core.models import ChunkType, Document


def _make_doc(content: str, source_id: str = "doc1") -> Document:
    return Document(
        id=source_id,
        workspace_id="ws_test",
        source_type="confluence",
        source_id=source_id,
        title="Test Doc",
        content=content,
    )


def _long_content() -> str:
    """Generate content long enough to trigger root-child splitting.

    Default chunk size is 1500 tokens (~6000 chars for Latin text).
    We need well over that to produce root + children.
    """
    paragraphs = []
    for i in range(40):
        sentences = [
            f"Section {i} paragraph about topic number {i}."
            f" This elaborates on the key concepts of area {i}."
            f" Additional detail about how component {i} integrates."
            f" Performance considerations for module {i} are documented here."
            f" The team reviewed and approved the design for feature {i}."
        ]
        paragraphs.append(" ".join(sentences))
    return "\n\n".join(paragraphs)


class TestHierarchicalIngestionEnabled:
    """Pipeline stores chunk_type and parent_id when hierarchical enabled."""

    @patch("metatron.ingestion.pipeline._register_persons")
    @patch("metatron.ingestion.pipeline._extract_graphs_parallel")
    @patch("metatron.ingestion.pipeline._write_chunk_hierarchy")
    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_stores_chunk_type_and_parent_id(
        self, mock_store_fn, mock_hierarchy, mock_graph, mock_persons,
    ) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = MagicMock()
        mock_store.delete_by_doc_labels.return_value = 0
        mock_store_fn.return_value = mock_store

        content = _long_content()
        doc = _make_doc(content)

        with patch("metatron.core.config.Settings") as mock_settings_cls:
            s = mock_settings_cls.return_value
            s.hierarchical_chunking_enabled = True
            s.graph_extraction_enabled = False

            ingest_documents([doc], workspace_id="ws_test")

        # Verify add_document was called with chunk_type/parent_id in metadata
        assert mock_store.add_document.call_count >= 2
        calls = mock_store.add_document.call_args_list

        # First call should be root chunk
        first_meta = calls[0].kwargs.get("metadata") or calls[0][1].get("metadata")
        assert first_meta["chunk_type"] == "root"

        # Subsequent calls should be child chunks with parent_id
        child_calls = calls[1:]
        for call in child_calls:
            meta = call.kwargs.get("metadata") or call[1].get("metadata")
            assert meta["chunk_type"] == "child"
            assert meta["parent_id"] != ""

    @patch("metatron.ingestion.pipeline._register_persons")
    @patch("metatron.ingestion.pipeline._extract_graphs_parallel")
    @patch("metatron.ingestion.pipeline._write_chunk_hierarchy")
    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_writes_chunk_hierarchy_to_memgraph(
        self, mock_store_fn, mock_hierarchy, mock_graph, mock_persons,
    ) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = MagicMock()
        mock_store.delete_by_doc_labels.return_value = 0
        mock_store_fn.return_value = mock_store

        content = _long_content()
        doc = _make_doc(content)

        with patch("metatron.core.config.Settings") as mock_settings_cls:
            s = mock_settings_cls.return_value
            s.hierarchical_chunking_enabled = True
            s.graph_extraction_enabled = False

            ingest_documents([doc], workspace_id="ws_test")

        mock_hierarchy.assert_called_once()
        call_args = mock_hierarchy.call_args
        chunk_objs = call_args[0][0]
        assert any(c.chunk_type == ChunkType.ROOT for c in chunk_objs)
        assert any(c.chunk_type == ChunkType.CHILD for c in chunk_objs)


class TestHierarchicalIngestionDisabled:
    """Pipeline uses simple_chunk() when hierarchical disabled."""

    @patch("metatron.ingestion.pipeline._register_persons")
    @patch("metatron.ingestion.pipeline._extract_graphs_parallel")
    @patch("metatron.ingestion.pipeline._write_chunk_hierarchy")
    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_uses_simple_chunk_when_disabled(
        self, mock_store_fn, mock_hierarchy, mock_graph, mock_persons,
    ) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = MagicMock()
        mock_store.delete_by_doc_labels.return_value = 0
        mock_store_fn.return_value = mock_store

        content = _long_content()
        doc = _make_doc(content)

        with patch("metatron.core.config.Settings") as mock_settings_cls:
            s = mock_settings_cls.return_value
            s.hierarchical_chunking_enabled = False
            s.graph_extraction_enabled = False

            ingest_documents([doc], workspace_id="ws_test")

        # All chunks should be standalone (simple_chunk)
        calls = mock_store.add_document.call_args_list
        for call in calls:
            meta = call.kwargs.get("metadata") or call[1].get("metadata")
            assert meta["chunk_type"] == "standalone"

        # Hierarchy write should NOT be called
        mock_hierarchy.assert_not_called()


class TestGracefulDegradation:
    """Ingestion continues when Memgraph is unavailable."""

    @patch("metatron.ingestion.pipeline._register_persons")
    @patch("metatron.ingestion.pipeline._extract_graphs_parallel")
    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_continues_when_memgraph_unavailable(
        self, mock_store_fn, mock_graph, mock_persons,
    ) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = MagicMock()
        mock_store.delete_by_doc_labels.return_value = 0
        mock_store_fn.return_value = mock_store

        content = _long_content()
        doc = _make_doc(content)

        with (
            patch("metatron.core.config.Settings") as mock_settings_cls,
            patch(
                "metatron.ingestion.pipeline._write_chunk_hierarchy",
                side_effect=Exception("Memgraph unavailable"),
            ),
        ):
            s = mock_settings_cls.return_value
            s.hierarchical_chunking_enabled = True
            s.graph_extraction_enabled = False

            result = ingest_documents([doc], workspace_id="ws_test")

        # Ingestion should succeed despite Memgraph failure
        # _write_chunk_hierarchy is called after store.add_document calls,
        # but its exception is caught inside the per-document try/except.
        # The document should still be counted (new_count incremented before
        # hierarchy write).
        assert result.documents_new == 1
        assert mock_store.add_document.call_count >= 1
