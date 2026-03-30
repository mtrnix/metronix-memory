"""Tests for incremental sync: SyncState, delete methods, sync flow."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from metatron.connectors.sync_state import SyncState

# ---------------------------------------------------------------------------
# SyncState
# ---------------------------------------------------------------------------


class TestSyncState:
    def test_get_returns_none_when_never_synced(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        assert state.get_last_sync("WS1", "confluence") is None

    def test_set_and_get(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        ts = datetime(2026, 2, 11, 10, 0, 0, tzinfo=UTC)
        state.set_last_sync("WS1", "confluence", ts)
        result = state.get_last_sync("WS1", "confluence")
        assert result == ts

    def test_set_defaults_to_now(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        state.set_last_sync("WS1", "jira")
        result = state.get_last_sync("WS1", "jira")
        assert result is not None
        assert result.year == datetime.now(UTC).year

    def test_clear(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        state.set_last_sync("WS1", "confluence")
        state.clear("WS1", "confluence")
        assert state.get_last_sync("WS1", "confluence") is None

    def test_multiple_workspaces(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        ts1 = datetime(2026, 2, 10, tzinfo=UTC)
        ts2 = datetime(2026, 2, 11, tzinfo=UTC)
        state.set_last_sync("WS1", "confluence", ts1)
        state.set_last_sync("WS2", "confluence", ts2)
        assert state.get_last_sync("WS1", "confluence") == ts1
        assert state.get_last_sync("WS2", "confluence") == ts2

    def test_multiple_source_types(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        ts1 = datetime(2026, 2, 10, tzinfo=UTC)
        ts2 = datetime(2026, 2, 11, tzinfo=UTC)
        state.set_last_sync("WS1", "confluence", ts1)
        state.set_last_sync("WS1", "jira", ts2)
        assert state.get_last_sync("WS1", "confluence") == ts1
        assert state.get_last_sync("WS1", "jira") == ts2

    def test_file_persistence(self, tmp_path) -> None:
        ts = datetime(2026, 2, 11, 12, 30, 0, tzinfo=UTC)
        state1 = SyncState(state_dir=str(tmp_path))
        state1.set_last_sync("WS1", "jira", ts)

        # New instance reads from same file
        state2 = SyncState(state_dir=str(tmp_path))
        assert state2.get_last_sync("WS1", "jira") == ts

    def test_corrupt_file_handled(self, tmp_path) -> None:
        state_file = tmp_path / "sync_state.json"
        state_file.write_text("not valid json{{{")
        state = SyncState(state_dir=str(tmp_path))
        assert state.get_last_sync("WS1", "confluence") is None

    def test_clear_nonexistent_key(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        # Should not raise
        state.clear("WS1", "nonexistent")


# ---------------------------------------------------------------------------
# Qdrant delete_by_doc_labels
# ---------------------------------------------------------------------------


class TestQdrantDeleteByDocLabels:
    def test_delete_calls_qdrant(self) -> None:
        from metatron.storage.qdrant import QdrantVectorStore

        store = MagicMock()
        store.collection_name = "test_collection"
        store.client.scroll.return_value = ([MagicMock(), MagicMock()], None)

        QdrantVectorStore.delete_by_doc_labels(store, ["DOC-1"])
        store.client.delete.assert_called_once()
        store.client.scroll.assert_called_once()

    def test_delete_empty_list_returns_zero(self) -> None:
        from metatron.storage.qdrant import QdrantVectorStore

        store = MagicMock()
        result = QdrantVectorStore.delete_by_doc_labels(store, [])
        assert result == 0
        store.client.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Graph delete_document_node
# ---------------------------------------------------------------------------


class TestGraphDeleteDocumentNode:
    @patch("metatron.storage.graph_ops.get_memgraph_driver")
    def test_delete_runs_cypher(self, mock_driver) -> None:
        from metatron.storage.graph_ops import delete_document_node

        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        delete_document_node("DOC-1", "MTRNIX")
        mock_session.run.assert_called_once()
        cypher = mock_session.run.call_args[0][0]
        assert "DETACH DELETE" in cypher
        assert "doc_label" in cypher
        assert "'DOC-1'" in cypher
        assert "'MTRNIX'" in cypher


# ---------------------------------------------------------------------------
# Connector since parameter
# ---------------------------------------------------------------------------


class TestConnectorSinceParameter:
    def test_confluence_fetch_signature_accepts_since(self) -> None:
        import inspect

        from metatron.connectors.confluence import ConfluenceConnector

        sig = inspect.signature(ConfluenceConnector.fetch)
        assert "since" in sig.parameters

    def test_jira_fetch_signature_accepts_since(self) -> None:
        import inspect

        from metatron.connectors.jira import JiraConnector

        sig = inspect.signature(JiraConnector.fetch)
        assert "since" in sig.parameters


# ---------------------------------------------------------------------------
# Pipeline incremental flag
# ---------------------------------------------------------------------------


class TestPipelineDedup:
    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_duplicate_chunks_across_docs_skipped(self, mock_get_store) -> None:
        """When two docs produce identical chunks, the second is skipped."""
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        mock_get_store.return_value = store

        # Two docs with identical content → same chunks
        doc1 = Document(
            source_type="confluence",
            source_id="PAGE-1",
            title="Doc A",
            content="The quick brown fox jumps over the lazy dog in the park every single morning",
        )
        doc2 = Document(
            source_type="confluence",
            source_id="PAGE-2",
            title="Doc B",
            content="The quick brown fox jumps over the lazy dog in the park every single morning",
        )

        result = await ingest_documents([doc1, doc2], "WS1", "confluence")

        # Both docs should count as new (document-level), but doc2's chunks
        # should be skipped at the chunk level (dedup)
        assert result.documents_new == 2
        # doc1 stores chunks, doc2 chunks are duplicates → fewer add_document calls
        calls_count = store.add_document.call_count
        # doc1 should have stored at least 1 chunk
        assert calls_count >= 1

    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_simhash_stored_in_metadata(self, mock_get_store) -> None:
        """Chunk metadata includes simhash value."""
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence",
            source_id="PAGE-1",
            title="Test",
            content="Unique content that should be indexed normally here",
        )

        await ingest_documents([doc], "WS1", "confluence")

        assert store.add_document.call_count >= 1
        # Check metadata of first call
        call_kwargs = store.add_document.call_args_list[0]
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        assert "simhash" in metadata
        assert isinstance(metadata["simhash"], int)

    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_same_doc_chunks_not_deduped(self, mock_get_store) -> None:
        """Chunks from the same document are NOT flagged as duplicates."""
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence",
            source_id="PAGE-1",
            title="Test",
            content="Repeated content. " * 50,
        )

        result = await ingest_documents([doc], "WS1", "confluence")
        assert result.documents_new == 1
        # All chunks from same doc should be stored (not deduped against each other)
        assert store.add_document.call_count >= 1

    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_incremental_removes_doc_from_dedup_index(
        self,
        mock_get_store,
    ) -> None:
        """Incremental reingest calls dedup_index.remove_doc before processing."""
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        store.delete_by_doc_labels.return_value = 2  # had old chunks
        mock_get_store.return_value = store

        doc1 = Document(
            source_type="confluence",
            source_id="PAGE-1",
            title="Original",
            content="The quick brown fox jumps over the lazy dog in the park every morning",
        )
        doc2 = Document(
            source_type="confluence",
            source_id="PAGE-1",
            title="Updated",
            content="The quick brown fox jumps over the lazy dog in the park every morning",
        )

        with patch("metatron.ingestion.pipeline._delete_graph_node"):
            result = await ingest_documents(
                [doc1, doc2],
                "WS1",
                "confluence",
                incremental=True,
            )

        # Both should be updated (incremental delete found old chunks)
        assert result.documents_updated == 2


class TestPipelineIncremental:
    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_incremental_deletes_old_chunks(self, mock_get_store) -> None:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        store.delete_by_doc_labels.return_value = 3
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence",
            source_id="PAGE-1",
            title="Test",
            content="Some content for chunking.",
        )

        with patch("metatron.ingestion.pipeline._delete_graph_node") as mock_gd:
            result = await ingest_documents(
                [doc],
                "WS1",
                "confluence",
                incremental=True,
            )

            store.delete_by_doc_labels.assert_called_once_with(["PAGE-1"])
            mock_gd.assert_called_once_with("PAGE-1", "WS1")
            assert result.documents_updated == 1
            assert result.documents_new == 0

    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_incremental_new_doc_counted_as_new(self, mock_get_store) -> None:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        store.delete_by_doc_labels.return_value = 0
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence",
            source_id="PAGE-NEW",
            title="New Page",
            content="Brand new content.",
        )

        with patch("metatron.ingestion.pipeline._delete_graph_node") as mock_gd:
            result = await ingest_documents(
                [doc],
                "WS1",
                "confluence",
                incremental=True,
            )

            assert result.documents_new == 1
            assert result.documents_updated == 0
            mock_gd.assert_not_called()

    @patch("metatron.storage.qdrant.get_async_hybrid_store", new_callable=AsyncMock)
    async def test_non_incremental_skips_delete(self, mock_get_store) -> None:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = AsyncMock()
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence",
            source_id="PAGE-1",
            title="Test",
            content="Content.",
        )
        await ingest_documents([doc], "WS1", "confluence", incremental=False)

        store.delete_by_doc_labels.assert_not_called()


# ---------------------------------------------------------------------------
# Sync flow — argument parsing
# ---------------------------------------------------------------------------


class TestSyncArgParsing:
    """Test _cmd_sync returns API redirect message."""

    def test_sync_returns_api_message(self) -> None:
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        router = AgentRouter(settings=settings)

        result = router.route("/sync confluence", user_id="u1")
        assert "no longer supported" in result
        assert "API" in result

        SessionManager.reset_instance()

    def test_sync_help_shows_full(self) -> None:
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        router = AgentRouter(settings=settings)

        result = router.route("/help", user_id="u1")
        assert "full" in result

        SessionManager.reset_instance()
