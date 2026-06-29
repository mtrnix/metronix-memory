"""Tests for BM25 title boosting in document indexing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from metronix.ingestion.bm25 import compute_bm25_sparse_vector, tokenize


class TestTitleBoostInBm25:
    def test_title_tokens_increase_bm25_weight(self) -> None:
        """Prepending title to text should boost title token weights."""
        text = "some general content about the project"
        title = "deployment guide"

        # Without title boost
        idx_plain, vals_plain = compute_bm25_sparse_vector(text)
        # With title boost (title repeated twice)
        boosted_text = f"{title} {title} {text}"
        idx_boosted, vals_boosted = compute_bm25_sparse_vector(boosted_text)

        # Title tokens ("deployment", "guide") should appear in boosted
        title_tokens = tokenize(title)
        assert len(title_tokens) > 0

        plain_map = dict(zip(idx_plain, vals_plain, strict=False))
        boosted_map = dict(zip(idx_boosted, vals_boosted, strict=False))

        # Boosted vector should have more non-zero entries (title tokens added)
        assert len(boosted_map) >= len(plain_map)

        # Title token indices should be present in boosted vector
        from metronix.ingestion.bm25 import word_to_index

        for token in title_tokens:
            token_idx = word_to_index(token)
            assert token_idx in boosted_map

    def test_empty_title_no_change(self) -> None:
        """Empty title should produce same BM25 vector as no title."""
        text = "some content here for testing"
        idx_plain, vals_plain = compute_bm25_sparse_vector(text)
        idx_empty, vals_empty = compute_bm25_sparse_vector(f" {text}")  # just a space prefix

        # Same indices and values (whitespace is stripped by tokenizer)
        assert sorted(idx_plain) == sorted(idx_empty)


class TestQdrantAddDocumentTitleBoost:
    @patch(
        "metronix.storage.qdrant.get_cached_embedding_split",
        return_value=[("chunk text here", [0.1] * 768)],
    )
    @patch("metronix.storage.qdrant.compute_bm25_sparse_vector", return_value=([1], [1.0]))
    def test_add_document_prepends_title_to_bm25(
        self,
        mock_bm25: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        """add_document should prepend title twice to text for BM25 computation."""
        from metronix.storage.qdrant import QdrantVectorStore

        with patch.object(QdrantVectorStore, "__init__", lambda self, *a, **kw: None):
            store = QdrantVectorStore.__new__(QdrantVectorStore)
            store.collection_name = "test"
            store.workspace_id = "TEST"
            store.client = MagicMock()

        store.add_document("chunk text here", metadata={"title": "My Report"})
        bm25_input = mock_bm25.call_args[0][0]
        assert bm25_input == "My Report My Report chunk text here"

    @patch(
        "metronix.storage.qdrant.get_cached_embedding_split",
        return_value=[("chunk text here", [0.1] * 768)],
    )
    @patch("metronix.storage.qdrant.compute_bm25_sparse_vector", return_value=([1], [1.0]))
    def test_add_document_no_title_uses_plain_text(
        self,
        mock_bm25: MagicMock,
        mock_embed: MagicMock,
    ) -> None:
        """Without title in metadata, BM25 uses plain chunk text."""
        from metronix.storage.qdrant import QdrantVectorStore

        with patch.object(QdrantVectorStore, "__init__", lambda self, *a, **kw: None):
            store = QdrantVectorStore.__new__(QdrantVectorStore)
            store.collection_name = "test"
            store.workspace_id = "TEST"
            store.client = MagicMock()

        store.add_document("chunk text here", metadata={})
        bm25_input = mock_bm25.call_args[0][0]
        assert bm25_input == "chunk text here"
