"""Tests for metatron.mcp.tools — all 5 MCP tool functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.mcp.tools.models import (
    SearchResponse,
    SearchResultItem,
    StatusResponse,
    StoreResponse,
    SyncResponse,
    SyncSourceResult,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_search_result_item(self) -> None:
        item = SearchResultItem(
            doc_label="DOC-1",
            title="Test",
            content="body",
            source_type="jira",
            score=0.9,
        )
        assert item.doc_label == "DOC-1"
        assert item.score == 0.9

    def test_search_response(self) -> None:
        resp = SearchResponse(results=[], has_more=False, total=0)
        d = resp.model_dump()
        assert d["total"] == 0
        assert d["has_more"] is False

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
# metatron_search
# ---------------------------------------------------------------------------


class TestMetatronSearch:
    @pytest.mark.asyncio
    async def test_returns_answer_from_pipeline(self) -> None:
        # Patch at the source module — lazy import resolves there
        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value="Found: document X. Sources: [1]",
        ):
            from metatron.mcp.tools.search import metatron_search

            result = await metatron_search(query="test query")
            assert "error" not in result
            assert result["total"] == 1
            assert "Found:" in result["results"][0]["content"]

    @pytest.mark.asyncio
    async def test_handles_exception(self) -> None:
        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            side_effect=RuntimeError("search failed"),
        ):
            from metatron.mcp.tools.search import metatron_search

            result = await metatron_search(query="broken")
            assert "error" in result
            assert "INTERNAL_ERROR" in result["error"]["code"]


# ---------------------------------------------------------------------------
# metatron_get
# ---------------------------------------------------------------------------


class TestMetatronGet:
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
            "metatron.storage.qdrant.get_hybrid_store",
            return_value=mock_store,
        ):
            from metatron.mcp.tools.get import metatron_get

            result = await metatron_get(doc_label="DOC-1")
            assert result["doc_label"] == "DOC-1"
            assert result["content"] == "Hello world"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        mock_store = MagicMock()
        mock_store.search_by_doc_labels.return_value = []
        with patch(
            "metatron.storage.qdrant.get_hybrid_store",
            return_value=mock_store,
        ):
            from metatron.mcp.tools.get import metatron_get

            result = await metatron_get(doc_label="NOPE-999")
            assert "error" in result
            assert result["error"]["code"] == "DOCUMENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_empty_label_raises(self) -> None:
        from metatron.mcp.tools.get import metatron_get

        result = await metatron_get(doc_label="")
        assert "error" in result


# ---------------------------------------------------------------------------
# metatron_store
# ---------------------------------------------------------------------------


class TestMetatronStore:
    @pytest.mark.asyncio
    async def test_stores_document(self) -> None:
        from unittest.mock import AsyncMock

        mock_result = MagicMock()
        mock_result.errors = []
        mock_result.documents_new = 2
        with patch(
            "metatron.ingestion.pipeline.ingest_documents",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            from metatron.mcp.tools.store import metatron_store

            result = await metatron_store(content="Remember this")
            assert result["success"] is True
            assert result["chunks_stored"] == 2
            assert result["doc_label"].startswith("MEM-")

    @pytest.mark.asyncio
    async def test_custom_doc_label(self) -> None:
        from unittest.mock import AsyncMock

        mock_result = MagicMock()
        mock_result.errors = []
        mock_result.documents_new = 1
        with patch(
            "metatron.ingestion.pipeline.ingest_documents",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            from metatron.mcp.tools.store import metatron_store

            result = await metatron_store(content="x", doc_label="MY-DOC")
            assert result["doc_label"] == "MY-DOC"

    @pytest.mark.asyncio
    async def test_empty_content_returns_error(self) -> None:
        from metatron.mcp.tools.store import metatron_store

        result = await metatron_store(content="")
        assert "error" in result


# ---------------------------------------------------------------------------
# metatron_status
# ---------------------------------------------------------------------------


class TestMetatronStatus:
    def _mock_settings(self) -> MagicMock:
        s = MagicMock()
        s.embedding_model = "nomic-embed-text"
        return s

    @pytest.mark.asyncio
    async def test_healthy_status(self) -> None:
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"chunk_count": 42, "file_count": 5}
        with (
            patch("metatron.storage.qdrant.get_hybrid_store", return_value=mock_store),
            patch("metatron.core.config.Settings", return_value=self._mock_settings()),
        ):
            from metatron.mcp.tools.status import metatron_status

            result = await metatron_status()
            assert result["status"] == "healthy"
            assert result["documents"]["total"] == 42

    @pytest.mark.asyncio
    async def test_initializing_when_empty(self) -> None:
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"chunk_count": 0, "file_count": 0}
        with (
            patch("metatron.storage.qdrant.get_hybrid_store", return_value=mock_store),
            patch("metatron.core.config.Settings", return_value=self._mock_settings()),
        ):
            from metatron.mcp.tools.status import metatron_status

            result = await metatron_status()
            assert result["status"] == "initializing"

    @pytest.mark.asyncio
    async def test_handles_store_error(self) -> None:
        with (
            patch(
                "metatron.storage.qdrant.get_hybrid_store",
                side_effect=ConnectionError("qdrant down"),
            ),
            patch("metatron.core.config.Settings", return_value=self._mock_settings()),
        ):
            from metatron.mcp.tools.status import metatron_status

            result = await metatron_status()
            assert result["status"] == "initializing"
