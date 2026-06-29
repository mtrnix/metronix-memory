"""Tests for ContextFetcher — fetching chunk data from Qdrant."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from metronix.benchmarker.services.context_fetcher import ContextFetcher


@pytest.fixture
def mock_settings():
    """Mock Settings object."""
    settings = MagicMock()
    settings.qdrant_host = "localhost"
    settings.qdrant_http_port = 6333
    return settings


class TestContextFetcherInitialization:
    """Test ContextFetcher initialization."""

    def test_init_default(self):
        """Test initialization with default parameters."""
        fetcher = ContextFetcher(
            qdrant_url="http://localhost:6333",
        )
        assert fetcher.qdrant_url == "http://localhost:6333"
        assert fetcher.collection == "mem_docs_hybrid"
        assert fetcher.timeout == 30.0

    def test_init_custom(self):
        """Test initialization with custom parameters."""
        fetcher = ContextFetcher(
            qdrant_url="http://qdrant:6333",
            qdrant_collection="custom_collection",
            timeout=60.0,
        )
        assert fetcher.qdrant_url == "http://qdrant:6333"
        assert fetcher.collection == "custom_collection"
        assert fetcher.timeout == 60.0

    def test_from_settings(self, mock_settings):
        """Test factory method from_settings."""
        fetcher = ContextFetcher.from_settings(mock_settings)
        assert "localhost" in fetcher.qdrant_url
        assert "6333" in fetcher.qdrant_url


class TestFetchChunks:
    """Test fetch_chunks method."""

    @pytest.mark.asyncio
    async def test_fetch_chunks_success(self):
        """Test successful chunk fetching."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")

        source_results = [
            {"id": "chunk1", "score": 0.9},
            {"id": "chunk2", "score": 0.8},
        ]

        mock_response_1 = MagicMock()
        mock_response_1.status_code = 200
        mock_response_1.json.return_value = {
            "result": {
                "id": "chunk1",
                "payload": {
                    "title": "Doc 1",
                    "data": "Content 1",
                    "doc_label": "doc1",
                    "chunk": 0,
                    "type": "text",
                },
            }
        }

        mock_response_2 = MagicMock()
        mock_response_2.status_code = 200
        mock_response_2.json.return_value = {
            "result": {
                "id": "chunk2",
                "payload": {
                    "title": "Doc 2",
                    "data": "Content 2",
                    "doc_label": "doc2",
                    "chunk": 1,
                    "type": "text",
                },
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.get = AsyncMock(side_effect=[mock_response_1, mock_response_2])
            mock_client.return_value = mock_instance

            chunks = await fetcher.fetch_chunks(source_results)

        assert len(chunks) == 2
        assert chunks[0].id == "chunk1"
        assert chunks[0].title == "Doc 1"
        assert chunks[0].data == "Content 1"
        assert chunks[0].score == 0.9
        assert chunks[1].id == "chunk2"
        assert chunks[1].score == 0.8

    @pytest.mark.asyncio
    async def test_fetch_chunks_empty_input(self):
        """Test with empty source_results."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")
        chunks = await fetcher.fetch_chunks([])
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_fetch_chunks_missing_ids(self):
        """Test with source_results missing ids."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")
        source_results = [
            {"score": 0.9},  # No id
            {"id": None, "score": 0.8},  # None id
        ]
        chunks = await fetcher.fetch_chunks(source_results)
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_fetch_chunks_404_not_found(self):
        """Test handling of 404 responses."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")

        source_results = [{"id": "chunk1", "score": 0.9}]

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            chunks = await fetcher.fetch_chunks(source_results)

        # Should skip 404 chunks
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_fetch_chunks_connection_error(self):
        """Test handling of connection errors."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")

        source_results = [{"id": "chunk1", "score": 0.9}]

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client.return_value = mock_instance

            chunks = await fetcher.fetch_chunks(source_results)

        # Should return empty list on connection error
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_fetch_chunks_unexpected_error(self):
        """Test handling of unexpected errors."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")

        source_results = [{"id": "chunk1", "score": 0.9}]

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.get = AsyncMock(side_effect=RuntimeError("Unexpected"))
            mock_client.return_value = mock_instance

            chunks = await fetcher.fetch_chunks(source_results)

        # Should return empty list on unexpected error
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_fetch_chunks_mixed_results(self):
        """Test with mix of successful and failed fetches."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")

        source_results = [
            {"id": "chunk1", "score": 0.9},
            {"id": "chunk2", "score": 0.8},
        ]

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "result": {
                "id": "chunk1",
                "payload": {
                    "title": "Doc 1",
                    "data": "Content 1",
                    "doc_label": "doc1",
                },
            }
        }

        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.get = AsyncMock(side_effect=[mock_response_success, mock_response_404])
            mock_client.return_value = mock_instance

            chunks = await fetcher.fetch_chunks(source_results)

        # Should only return successful chunk
        assert len(chunks) == 1
        assert chunks[0].id == "chunk1"


class TestParseChunk:
    """Test _parse_chunk static method."""

    def test_parse_chunk_full_data(self):
        """Test parsing chunk with all fields."""
        point_data = {
            "id": "chunk1",
            "payload": {
                "title": "Test Doc",
                "data": "Test content",
                "doc_label": "doc1",
                "chunk": 5,
                "type": "text",
            },
        }

        chunk = ContextFetcher._parse_chunk(point_data, score=0.95)

        assert chunk.id == "chunk1"
        assert chunk.title == "Test Doc"
        assert chunk.data == "Test content"
        assert chunk.doc_label == "doc1"
        assert chunk.score == 0.95
        assert chunk.chunk_num == 5
        assert chunk.type == "text"

    def test_parse_chunk_minimal_data(self):
        """Test parsing chunk with minimal fields."""
        point_data = {
            "id": "chunk1",
            "payload": {},
        }

        chunk = ContextFetcher._parse_chunk(point_data)

        assert chunk.id == "chunk1"
        assert chunk.title == "N/A"
        assert chunk.data == ""
        assert chunk.doc_label == ""
        assert chunk.score is None

    def test_parse_chunk_missing_payload(self):
        """Test parsing chunk with missing payload."""
        point_data = {"id": "chunk1"}

        chunk = ContextFetcher._parse_chunk(point_data)

        assert chunk.id == "chunk1"
        assert chunk.title == "N/A"


class TestStringRepresentation:
    """Test string representations."""

    def test_str(self):
        """Test __str__ method."""
        fetcher = ContextFetcher(qdrant_url="http://localhost:6333")
        result = str(fetcher)
        assert "ContextFetcher" in result
        assert "localhost" in result

    def test_repr(self):
        """Test __repr__ method."""
        fetcher = ContextFetcher(
            qdrant_url="http://localhost:6333",
            qdrant_collection="custom",
        )
        result = repr(fetcher)
        assert "ContextFetcher" in result
        assert "localhost" in result
        assert "custom" in result
