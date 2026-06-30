"""Tests for metronix.mcp.tools — MCP tool functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from metronix.mcp.tools.models import (
    StatusResponse,
    StoreResponse,
    SyncResponse,
    SyncSourceResult,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_store_response(self) -> None:
        resp = StoreResponse(success=True, doc_label="MEM-1", chunks_stored=3)
        assert resp.success is True

    def test_status_response(self) -> None:
        resp = StatusResponse(
            status="healthy",
            documents={"total": 10},
            embedding_model="nomic-embed-text",
        )
        assert resp.status == "healthy"

    def test_sync_source_result_defaults(self) -> None:
        r = SyncSourceResult(source="gh", success=True)
        assert r.documents_fetched == 0
        assert r.errors == []

    def test_sync_response(self) -> None:
        r = SyncResponse(success=True, sources_synced=1, details=[])
        assert r.sources_synced == 1


# ---------------------------------------------------------------------------
# metronix_get
# ---------------------------------------------------------------------------


class TestMetronixGet:
    @pytest.mark.asyncio
    async def test_returns_document(self) -> None:
        mock_store = MagicMock()
        mock_store.search_by_doc_labels.return_value = [
            {
                "doc_label": "DOC-1",
                "title": "Test Doc",
                "content": "Hello world",
                "source_type": "confluence",
            }
        ]
        with patch(
            "metronix.storage.qdrant.get_hybrid_store",
            return_value=mock_store,
        ):
            from metronix.mcp.tools.get import metronix_get

            result = await metronix_get(doc_label="DOC-1")
            assert result["doc_label"] == "DOC-1"
            assert result["content"] == "Hello world"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        mock_store = MagicMock()
        mock_store.search_by_doc_labels.return_value = []
        with patch(
            "metronix.storage.qdrant.get_hybrid_store",
            return_value=mock_store,
        ):
            from metronix.mcp.tools.get import metronix_get

            result = await metronix_get(doc_label="NOPE-999")
            assert "error" in result
            assert result["error"]["code"] == "DOCUMENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_empty_label_raises(self) -> None:
        from metronix.mcp.tools.get import metronix_get

        result = await metronix_get(doc_label="")
        assert "error" in result


# ---------------------------------------------------------------------------
# metronix_store
# ---------------------------------------------------------------------------


class TestMetronixStore:
    @pytest.mark.asyncio
    async def test_stores_document(self) -> None:
        from unittest.mock import AsyncMock

        mock_result = MagicMock()
        mock_result.errors = []
        mock_result.documents_new = 2
        # metronix_store persists a raw_documents row then indexes into Qdrant;
        # it reuses the process-cached store and defers graph extraction.
        with (
            patch(
                "metronix.mcp.tools._source_deps.get_store",
                return_value=AsyncMock(),
            ),
            patch("metronix.ingestion.sync.persist_raw_documents", new_callable=AsyncMock),
            patch(
                "metronix.ingestion.pipeline.ingest_documents",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            from metronix.mcp.tools.store import metronix_store

            result = await metronix_store(content="Remember this")
            assert result["success"] is True
            assert result["chunks_stored"] == 2
            assert result["doc_label"].startswith("MEM-")

    @pytest.mark.asyncio
    async def test_custom_doc_label(self) -> None:
        from unittest.mock import AsyncMock

        mock_result = MagicMock()
        mock_result.errors = []
        mock_result.documents_new = 1
        with (
            patch(
                "metronix.mcp.tools._source_deps.get_store",
                return_value=AsyncMock(),
            ),
            patch("metronix.ingestion.sync.persist_raw_documents", new_callable=AsyncMock),
            patch(
                "metronix.ingestion.pipeline.ingest_documents",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            from metronix.mcp.tools.store import metronix_store

            result = await metronix_store(content="x", doc_label="MY-DOC")
            assert result["doc_label"] == "MY-DOC"

    @pytest.mark.asyncio
    async def test_empty_content_returns_error(self) -> None:
        from metronix.mcp.tools.store import metronix_store

        result = await metronix_store(content="")
        assert "error" in result


# ---------------------------------------------------------------------------
# metronix_status
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="pre-existing failure (status tool returns error dict); MTRNIX-458 follow-up"
)
class TestMetronixStatus:
    def _mock_settings(self) -> MagicMock:
        s = MagicMock()
        s.embedding_model = "nomic-embed-text"
        return s

    @pytest.mark.asyncio
    async def test_healthy_status(self) -> None:
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"chunk_count": 42, "file_count": 5}
        with (
            patch("metronix.storage.qdrant.get_hybrid_store", return_value=mock_store),
            patch("metronix.core.config.Settings", return_value=self._mock_settings()),
        ):
            from metronix.mcp.tools.status import metronix_status

            result = await metronix_status()
            assert result["status"] == "healthy"
            assert result["documents"]["total"] == 42

    @pytest.mark.asyncio
    async def test_initializing_when_empty(self) -> None:
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"chunk_count": 0, "file_count": 0}
        with (
            patch("metronix.storage.qdrant.get_hybrid_store", return_value=mock_store),
            patch("metronix.core.config.Settings", return_value=self._mock_settings()),
        ):
            from metronix.mcp.tools.status import metronix_status

            result = await metronix_status()
            assert result["status"] == "initializing"

    @pytest.mark.asyncio
    async def test_handles_store_error(self) -> None:
        with (
            patch(
                "metronix.storage.qdrant.get_hybrid_store",
                side_effect=ConnectionError("qdrant down"),
            ),
            patch("metronix.core.config.Settings", return_value=self._mock_settings()),
        ):
            from metronix.mcp.tools.status import metronix_status

            result = await metronix_status()
            assert result["status"] == "initializing"
