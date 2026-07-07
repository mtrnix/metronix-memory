"""Tests for metronix.ingestion.store.store_document — shared by the
metronix_store MCP tool and POST /api/v1/knowledge/store."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_store_document_success():
    mock_result = MagicMock()
    mock_result.errors = []
    mock_result.documents_new = 2
    mock_store = AsyncMock()

    with (
        patch("metronix.ingestion.sync.persist_raw_documents", new_callable=AsyncMock),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        from metronix.ingestion.store import store_document

        success, doc_label, chunks_stored = await store_document(
            mock_store,
            workspace_id="ws-test",
            content="hello world",
            doc_label="MY-DOC",
        )

    assert success is True
    assert doc_label == "MY-DOC"
    assert chunks_stored == 2
    mock_store.mark_documents_synced_by_source.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_document_auto_generates_doc_label():
    mock_result = MagicMock()
    mock_result.errors = []
    mock_result.documents_new = 1
    mock_store = AsyncMock()

    with (
        patch("metronix.ingestion.sync.persist_raw_documents", new_callable=AsyncMock),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        from metronix.ingestion.store import store_document

        _, doc_label, _ = await store_document(mock_store, workspace_id="ws-test", content="hello")

    assert doc_label.startswith("MEM-")


@pytest.mark.asyncio
async def test_store_document_rejects_empty_content():
    from metronix.ingestion.store import store_document

    with pytest.raises(ValueError, match="content is required"):
        await store_document(AsyncMock(), workspace_id="ws-test", content="   ")


@pytest.mark.asyncio
async def test_store_document_threads_source_type_through_pipeline():
    mock_result = MagicMock()
    mock_result.errors = []
    mock_result.documents_new = 1
    mock_store = AsyncMock()

    with (
        patch(
            "metronix.ingestion.sync.persist_raw_documents", new_callable=AsyncMock
        ) as mock_persist,
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_ingest,
    ):
        from metronix.ingestion.store import store_document

        await store_document(
            mock_store,
            workspace_id="ws-test",
            content="wiki page body",
            source_type="hermes_llm_wiki",
        )

    assert mock_persist.await_args.args[2] == "hermes_llm_wiki"
    assert mock_ingest.await_args.kwargs["connector_type"] == "hermes_llm_wiki"
    mock_store.mark_documents_synced_by_source.assert_awaited_once_with(
        workspace_id="ws-test",
        connector_type="hermes_llm_wiki",
        source_ids=[mock_persist.await_args.args[4][0].source_id],
        target="qdrant",
    )
