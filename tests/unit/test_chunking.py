"""Tests for ingestion/chunking.py — root-child and simple chunking."""

from __future__ import annotations

from metronix.core.models import ChunkType
from metronix.ingestion.chunking import root_child_chunk, simple_chunk


class TestRootChildChunk:
    def test_empty_text_returns_empty(self) -> None:
        result = root_child_chunk("", "doc1", "ws1")
        assert result == []

    def test_whitespace_only_returns_empty(self) -> None:
        result = root_child_chunk("   \n\t  ", "doc1", "ws1")
        assert result == []

    def test_short_text_returns_standalone(self) -> None:
        text = "This is a short document."
        result = root_child_chunk(text, "doc1", "ws1", max_tokens=100)
        assert len(result) == 1
        assert result[0].chunk_type == ChunkType.STANDALONE
        assert result[0].document_id == "doc1"
        assert result[0].workspace_id == "ws1"

    def test_long_text_returns_root_plus_children(self) -> None:
        # Generate text long enough to need splitting
        sentences = [f"Sentence number {i} with some extra words." for i in range(50)]
        text = " ".join(sentences)
        result = root_child_chunk(text, "doc1", "ws1", max_tokens=30, root_max_tokens=15)
        assert len(result) >= 2
        assert result[0].chunk_type == ChunkType.ROOT
        for child in result[1:]:
            assert child.chunk_type == ChunkType.CHILD
            assert child.parent_id == result[0].id

    def test_all_chunks_have_correct_workspace(self) -> None:
        sentences = [f"Sentence {i} is here." for i in range(30)]
        text = " ".join(sentences)
        result = root_child_chunk(text, "doc1", "ws_abc", max_tokens=20)
        for chunk in result:
            assert chunk.workspace_id == "ws_abc"
            assert chunk.document_id == "doc1"

    def test_chunk_content_is_nonempty(self) -> None:
        sentences = [f"Important fact number {i}." for i in range(20)]
        text = " ".join(sentences)
        result = root_child_chunk(text, "doc1", "ws1", max_tokens=25)
        for chunk in result:
            assert len(chunk.content.strip()) > 0
            assert chunk.token_count > 0


class TestSimpleChunk:
    def test_empty_text_returns_empty(self) -> None:
        result = simple_chunk("", "doc1", "ws1")
        assert result == []

    def test_short_text_single_chunk(self) -> None:
        text = "A brief document."
        result = simple_chunk(text, "doc1", "ws1", max_tokens=100)
        assert len(result) == 1
        assert result[0].chunk_type == ChunkType.STANDALONE

    def test_all_chunks_are_standalone(self) -> None:
        sentences = [f"Statement {i} goes here." for i in range(30)]
        text = " ".join(sentences)
        result = simple_chunk(text, "doc1", "ws1", max_tokens=20)
        assert len(result) > 1
        for chunk in result:
            assert chunk.chunk_type == ChunkType.STANDALONE
            assert chunk.parent_id is None

    def test_no_sentence_boundary_text(self) -> None:
        # Text without sentence-ending punctuation
        text = "word " * 100
        result = simple_chunk(text.strip(), "doc1", "ws1", max_tokens=20)
        assert len(result) >= 1
        for chunk in result:
            assert chunk.content.strip() != ""
