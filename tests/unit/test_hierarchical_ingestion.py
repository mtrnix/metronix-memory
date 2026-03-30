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


class TestEnsureCollection:
    """_ensure_collection() is called after get_hybrid_store() in ingest_documents()."""

    @patch("metatron.ingestion.pipeline._register_persons")
    @patch("metatron.ingestion.pipeline._extract_graphs_parallel")
    @patch("metatron.ingestion.pipeline._write_chunk_hierarchy")
    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_ensure_collection_called_after_get_hybrid_store(
        self, mock_store_fn, mock_hierarchy, mock_graph, mock_persons,
    ) -> None:
        from metatron.ingestion.pipeline import ingest_documents

        mock_store = MagicMock()
        mock_store.delete_by_doc_labels.return_value = 0
        mock_store_fn.return_value = mock_store

        doc = _make_doc("some content")

        with patch("metatron.core.config.Settings") as mock_settings_cls:
            s = mock_settings_cls.return_value
            s.hierarchical_chunking_enabled = False
            s.graph_extraction_enabled = False

            ingest_documents([doc], workspace_id="ws_test")

        mock_store._ensure_collection.assert_called_once()


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


class TestGraphRetry:
    """Failed graph writes are retried sequentially after parallel extraction."""

    def test_retry_recovers_failed_graph_writes(self) -> None:
        from metatron.ingestion.pipeline import _extract_graphs_parallel

        doc1 = _make_doc("A" * 200, source_id="doc1")
        doc2 = _make_doc("B" * 200, source_id="doc2")
        queue = [(doc1, "ws"), (doc2, "ws")]

        call_count: dict[str, int] = {"doc1": 0, "doc2": 0}

        def flaky_write(doc: Document, ws_id: str) -> None:
            call_count[doc.source_id] += 1
            # doc1 fails on first call (parallel), succeeds on retry
            if doc.source_id == "doc1" and call_count["doc1"] == 1:
                raise ConnectionError("Memgraph down")

        with patch("metatron.ingestion.pipeline._write_jira_to_graph"), patch(
            "metatron.ingestion.pipeline._write_doc_to_graph",
            side_effect=flaky_write,
        ):
            result = _extract_graphs_parallel(queue, max_workers=1)

        assert result["ok"] == 2
        assert result["errors"] == 0

    def test_retry_still_counts_persistent_failures(self) -> None:
        from metatron.ingestion.pipeline import _extract_graphs_parallel

        doc = _make_doc("A" * 200, source_id="doc1")
        queue = [(doc, "ws")]

        with patch("metatron.ingestion.pipeline._write_jira_to_graph"), patch(
            "metatron.ingestion.pipeline._write_doc_to_graph",
            side_effect=ConnectionError("Memgraph permanently down"),
        ):
            result = _extract_graphs_parallel(queue, max_workers=1)

        # Still fails after retry
        assert result["errors"] == 1
        assert result["ok"] == 0
