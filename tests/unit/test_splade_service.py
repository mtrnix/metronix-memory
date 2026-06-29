"""Tests for SPLADE microservice client and dispatch logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCallSpladeService:
    """Test the _call_splade_service HTTP client helper."""

    def test_call_splade_service_success(self):
        """Mock httpx, verify returns indices/values."""
        import metronix.storage.qdrant as qdrant_mod

        # Reset singleton
        qdrant_mod._splade_http_client = None

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "indices": [10, 42, 100],
            "values": [0.5, 1.2, 0.3],
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            indices, values = qdrant_mod._call_splade_service(
                "http://splade:8080", "/sparse/document", "test text"
            )

        assert indices == [10, 42, 100]
        assert values == [0.5, 1.2, 0.3]
        mock_client.post.assert_called_once_with(
            "http://splade:8080/sparse/document",
            json={"text": "test text"},
        )
        mock_response.raise_for_status.assert_called_once()

        # Cleanup singleton
        qdrant_mod._splade_http_client = None

    def test_call_splade_service_with_max_length(self):
        """When max_length is provided, it is included in payload."""
        import metronix.storage.qdrant as qdrant_mod

        qdrant_mod._splade_http_client = None

        mock_response = MagicMock()
        mock_response.json.return_value = {"indices": [1], "values": [0.5]}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            qdrant_mod._call_splade_service(
                "http://splade:8080", "/sparse/query", "q", max_length=64
            )

        mock_client.post.assert_called_once_with(
            "http://splade:8080/sparse/query",
            json={"text": "q", "max_length": 64},
        )

        qdrant_mod._splade_http_client = None

    def test_call_splade_service_failure_raises(self):
        """When httpx raises, error propagates (caller handles fallback)."""
        import httpx

        import metronix.storage.qdrant as qdrant_mod

        qdrant_mod._splade_http_client = None

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("connection refused")

        with patch("httpx.Client", return_value=mock_client):  # noqa: SIM117
            with pytest.raises(httpx.ConnectError):
                qdrant_mod._call_splade_service("http://splade:8080", "/sparse/document", "text")

        qdrant_mod._splade_http_client = None


class TestDispatchWithService:
    """Test SPLADE dispatch prefers service URL over local model."""

    def test_dispatch_prefers_service_url(self, settings):
        """When splade_service_url is set, calls service not local model."""
        settings.splade_enabled = True
        settings.splade_service_url = "http://splade:8080"

        with (
            patch("metronix.storage.qdrant.get_settings", return_value=settings),
            patch(
                "metronix.storage.qdrant._call_splade_service",
                return_value=([10, 42], [0.5, 1.2]),
            ) as mock_service,
        ):
            from metronix.storage.qdrant import _compute_doc_sparse

            result = _compute_doc_sparse("test text")

        mock_service.assert_called_once_with("http://splade:8080", "/sparse/document", "test text")
        assert result == ([10, 42], [0.5, 1.2])

    def test_dispatch_query_prefers_service_url(self, settings):
        """Query dispatch also prefers service URL."""
        settings.splade_enabled = True
        settings.splade_service_url = "http://splade:8080"

        with (
            patch("metronix.storage.qdrant.get_settings", return_value=settings),
            patch(
                "metronix.storage.qdrant._call_splade_service",
                return_value=([10], [0.8]),
            ) as mock_service,
        ):
            from metronix.storage.qdrant import _compute_query_sparse

            result = _compute_query_sparse("test query")

        mock_service.assert_called_once_with("http://splade:8080", "/sparse/query", "test query")
        assert result == ([10], [0.8])

    def test_dispatch_service_failure_fallback_to_bm25(self, settings):
        """When service call fails, falls back to BM25."""
        settings.splade_enabled = True
        settings.splade_service_url = "http://splade:8080"

        with (
            patch("metronix.storage.qdrant.get_settings", return_value=settings),
            patch(
                "metronix.storage.qdrant._call_splade_service",
                side_effect=Exception("connection refused"),
            ),
            patch(
                "metronix.storage.qdrant.compute_bm25_sparse_vector",
                return_value=([1, 2], [0.5, 0.6]),
            ) as mock_bm25,
        ):
            from metronix.storage.qdrant import _compute_doc_sparse

            result = _compute_doc_sparse("test text")

        mock_bm25.assert_called_once_with("test text")
        assert result == ([1, 2], [0.5, 0.6])

    def test_dispatch_no_url_uses_local(self, settings):
        """When splade_service_url is empty, uses local model."""
        settings.splade_enabled = True
        settings.splade_service_url = ""

        with (
            patch("metronix.storage.qdrant.get_settings", return_value=settings),
            patch(
                "metronix.ingestion.splade.compute_splade_sparse_vector",
                return_value=([10, 42], [0.5, 1.2]),
            ) as mock_local,
        ):
            from metronix.storage.qdrant import _compute_doc_sparse

            result = _compute_doc_sparse("test text")

        mock_local.assert_called_once_with("test text")
        assert result == ([10, 42], [0.5, 1.2])
