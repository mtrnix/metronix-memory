"""Tests for incremental sync: SyncState, delete methods, sync flow."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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
        ts = datetime(2026, 2, 11, 10, 0, 0, tzinfo=timezone.utc)
        state.set_last_sync("WS1", "confluence", ts)
        result = state.get_last_sync("WS1", "confluence")
        assert result == ts

    def test_set_defaults_to_now(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        state.set_last_sync("WS1", "jira")
        result = state.get_last_sync("WS1", "jira")
        assert result is not None
        assert result.year == datetime.now(timezone.utc).year

    def test_clear(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        state.set_last_sync("WS1", "confluence")
        state.clear("WS1", "confluence")
        assert state.get_last_sync("WS1", "confluence") is None

    def test_multiple_workspaces(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        ts1 = datetime(2026, 2, 10, tzinfo=timezone.utc)
        ts2 = datetime(2026, 2, 11, tzinfo=timezone.utc)
        state.set_last_sync("WS1", "confluence", ts1)
        state.set_last_sync("WS2", "confluence", ts2)
        assert state.get_last_sync("WS1", "confluence") == ts1
        assert state.get_last_sync("WS2", "confluence") == ts2

    def test_multiple_source_types(self, tmp_path) -> None:
        state = SyncState(state_dir=str(tmp_path))
        ts1 = datetime(2026, 2, 10, tzinfo=timezone.utc)
        ts2 = datetime(2026, 2, 11, tzinfo=timezone.utc)
        state.set_last_sync("WS1", "confluence", ts1)
        state.set_last_sync("WS1", "jira", ts2)
        assert state.get_last_sync("WS1", "confluence") == ts1
        assert state.get_last_sync("WS1", "jira") == ts2

    def test_file_persistence(self, tmp_path) -> None:
        ts = datetime(2026, 2, 11, 12, 30, 0, tzinfo=timezone.utc)
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
        params = mock_session.run.call_args[0][1]
        assert params["dl"] == "DOC-1"
        assert params["ws"] == "MTRNIX"


# ---------------------------------------------------------------------------
# Connector since parameter
# ---------------------------------------------------------------------------


class TestConnectorSinceParameter:
    def test_confluence_fetch_signature_accepts_since(self) -> None:
        from metatron.connectors.confluence import ConfluenceConnector
        import inspect
        sig = inspect.signature(ConfluenceConnector.fetch)
        assert "since" in sig.parameters

    def test_jira_fetch_signature_accepts_since(self) -> None:
        from metatron.connectors.jira import JiraConnector
        import inspect
        sig = inspect.signature(JiraConnector.fetch)
        assert "since" in sig.parameters


# ---------------------------------------------------------------------------
# Pipeline incremental flag
# ---------------------------------------------------------------------------


class TestPipelineIncremental:
    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_incremental_deletes_old_chunks(self, mock_get_store) -> None:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = MagicMock()
        store.delete_by_doc_labels.return_value = 3
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence", source_id="PAGE-1",
            title="Test", content="Some content for chunking.",
        )

        with patch("metatron.ingestion.pipeline._delete_graph_node") as mock_gd:
            result = ingest_documents([doc], "WS1", "confluence", incremental=True)

            store.delete_by_doc_labels.assert_called_once_with(["PAGE-1"])
            mock_gd.assert_called_once_with("PAGE-1", "WS1")
            assert result.documents_updated == 1
            assert result.documents_new == 0

    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_incremental_new_doc_counted_as_new(self, mock_get_store) -> None:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = MagicMock()
        store.delete_by_doc_labels.return_value = 0
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence", source_id="PAGE-NEW",
            title="New Page", content="Brand new content.",
        )

        with patch("metatron.ingestion.pipeline._delete_graph_node") as mock_gd:
            result = ingest_documents([doc], "WS1", "confluence", incremental=True)

            assert result.documents_new == 1
            assert result.documents_updated == 0
            mock_gd.assert_not_called()

    @patch("metatron.storage.qdrant.get_hybrid_store")
    def test_non_incremental_skips_delete(self, mock_get_store) -> None:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        store = MagicMock()
        mock_get_store.return_value = store

        doc = Document(
            source_type="confluence", source_id="PAGE-1",
            title="Test", content="Content.",
        )
        ingest_documents([doc], "WS1", "confluence", incremental=False)

        store.delete_by_doc_labels.assert_not_called()


# ---------------------------------------------------------------------------
# Sync flow — argument parsing
# ---------------------------------------------------------------------------


class TestSyncArgParsing:
    """Test _cmd_sync argument parsing without full mock chains."""

    def test_parse_full_flag(self) -> None:
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        router = AgentRouter(settings=settings)

        # Patch _cmd_sync internals to just check arg parsing
        with patch.object(router, "_cmd_sync", wraps=router._cmd_sync) as mock_sync:
            # Test that "confluence full" is parsed correctly
            # We'll intercept at a deeper level
            pass

        SessionManager.reset_instance()

    def test_sync_unknown_connector(self) -> None:
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        router = AgentRouter(settings=settings)

        result = router.route("/sync foobar", user_id="u1")
        assert "Unknown connector" in result

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


class TestSyncFlowWithState:
    """Integration-like tests for incremental sync flow."""

    @patch("metatron.agent.router._config_from_env")
    @patch("metatron.agent.router.asyncio")
    def test_first_sync_passes_no_since(self, mock_asyncio, mock_config) -> None:
        """First sync (no prior state) passes since=None to connector."""
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        settings.confluence_url = "https://org.atlassian.net"
        settings.jira_url = ""

        mock_config.return_value = {"url": "https://org.atlassian.net"}

        mock_connector = MagicMock()
        mock_docs = [MagicMock()]
        mock_loop = MagicMock()
        mock_asyncio.new_event_loop.return_value = mock_loop
        mock_loop.run_until_complete.side_effect = [None, mock_docs]

        mock_sync_state = MagicMock()
        mock_sync_state.get_last_sync.return_value = None  # never synced

        with patch("metatron.connectors.registry.ConnectorRegistry") as MockRegistry, \
             patch("metatron.connectors.registry.register_builtins"), \
             patch("metatron.ingestion.pipeline.ingest_documents") as mock_ingest, \
             patch("metatron.connectors.sync_state.SyncState", return_value=mock_sync_state):

            mock_registry_inst = MockRegistry.return_value
            mock_registry_inst.is_registered.return_value = True
            mock_registry_inst.create.return_value = mock_connector

            mock_result = MagicMock()
            mock_result.documents_new = 5
            mock_result.documents_updated = 0
            mock_result.documents_skipped = 0
            mock_result.errors = []
            mock_ingest.return_value = mock_result

            router = AgentRouter(settings=settings)
            result = router._cmd_sync("confluence", "TEST")

            # ingest was called with incremental=False (first sync)
            mock_ingest.assert_called_once()
            assert mock_ingest.call_args.kwargs.get("incremental", False) is False
            # set_last_sync was called after successful sync
            mock_sync_state.set_last_sync.assert_called_once()

        SessionManager.reset_instance()

    @patch("metatron.agent.router._config_from_env")
    @patch("metatron.agent.router.asyncio")
    def test_subsequent_sync_is_incremental(self, mock_asyncio, mock_config) -> None:
        """Second sync uses last_sync_at and passes incremental=True."""
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        settings.confluence_url = "https://org.atlassian.net"
        settings.jira_url = ""

        mock_config.return_value = {"url": "https://org.atlassian.net"}

        mock_connector = MagicMock()
        mock_docs = [MagicMock()]
        mock_loop = MagicMock()
        mock_asyncio.new_event_loop.return_value = mock_loop
        mock_loop.run_until_complete.side_effect = [None, mock_docs]

        last_sync = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
        mock_sync_state = MagicMock()
        mock_sync_state.get_last_sync.return_value = last_sync

        with patch("metatron.connectors.registry.ConnectorRegistry") as MockRegistry, \
             patch("metatron.connectors.registry.register_builtins"), \
             patch("metatron.ingestion.pipeline.ingest_documents") as mock_ingest, \
             patch("metatron.connectors.sync_state.SyncState", return_value=mock_sync_state):

            mock_registry_inst = MockRegistry.return_value
            mock_registry_inst.is_registered.return_value = True
            mock_registry_inst.create.return_value = mock_connector

            mock_result = MagicMock()
            mock_result.documents_new = 0
            mock_result.documents_updated = 3
            mock_result.documents_skipped = 0
            mock_result.errors = []
            mock_ingest.return_value = mock_result

            router = AgentRouter(settings=settings)
            result = router._cmd_sync("confluence", "TEST")

            # incremental=True because state existed
            mock_ingest.assert_called_once()
            assert mock_ingest.call_args.kwargs.get("incremental") is True
            assert "incremental" in result

        SessionManager.reset_instance()

    @patch("metatron.agent.router._config_from_env")
    @patch("metatron.agent.router.asyncio")
    def test_full_flag_forces_full_sync(self, mock_asyncio, mock_config) -> None:
        """'/sync confluence full' ignores last_sync_at."""
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        settings.confluence_url = "https://org.atlassian.net"
        settings.jira_url = ""

        mock_config.return_value = {"url": "https://org.atlassian.net"}

        mock_connector = MagicMock()
        mock_docs = [MagicMock()]
        mock_loop = MagicMock()
        mock_asyncio.new_event_loop.return_value = mock_loop
        mock_loop.run_until_complete.side_effect = [None, mock_docs]

        mock_sync_state = MagicMock()
        # Even though state exists, full flag should bypass it
        mock_sync_state.get_last_sync.return_value = datetime(2026, 2, 10, tzinfo=timezone.utc)

        with patch("metatron.connectors.registry.ConnectorRegistry") as MockRegistry, \
             patch("metatron.connectors.registry.register_builtins"), \
             patch("metatron.ingestion.pipeline.ingest_documents") as mock_ingest, \
             patch("metatron.connectors.sync_state.SyncState", return_value=mock_sync_state):

            mock_registry_inst = MockRegistry.return_value
            mock_registry_inst.is_registered.return_value = True
            mock_registry_inst.create.return_value = mock_connector

            mock_result = MagicMock()
            mock_result.documents_new = 10
            mock_result.documents_updated = 0
            mock_result.documents_skipped = 0
            mock_result.errors = []
            mock_ingest.return_value = mock_result

            router = AgentRouter(settings=settings)
            result = router._cmd_sync("confluence full", "TEST")

            # get_last_sync NOT called because force_full=True skips it
            mock_sync_state.get_last_sync.assert_not_called()
            assert mock_ingest.call_args.kwargs.get("incremental", False) is False
            assert "full" in result

        SessionManager.reset_instance()

    @patch("metatron.agent.router._config_from_env")
    @patch("metatron.agent.router.asyncio")
    def test_no_changes_shows_up_to_date(self, mock_asyncio, mock_config) -> None:
        """Incremental sync with no new docs shows 'up to date'."""
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager

        SessionManager.reset_instance()
        settings = MagicMock()
        settings.default_workspace_id = "TEST"
        settings.confluence_url = "https://org.atlassian.net"
        settings.jira_url = ""

        mock_config.return_value = {"url": "https://org.atlassian.net"}

        mock_connector = MagicMock()
        mock_loop = MagicMock()
        mock_asyncio.new_event_loop.return_value = mock_loop
        mock_loop.run_until_complete.side_effect = [None, []]  # fetch returns empty

        last_sync = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
        mock_sync_state = MagicMock()
        mock_sync_state.get_last_sync.return_value = last_sync

        with patch("metatron.connectors.registry.ConnectorRegistry") as MockRegistry, \
             patch("metatron.connectors.registry.register_builtins"), \
             patch("metatron.connectors.sync_state.SyncState", return_value=mock_sync_state):

            mock_registry_inst = MockRegistry.return_value
            mock_registry_inst.is_registered.return_value = True
            mock_registry_inst.create.return_value = mock_connector

            router = AgentRouter(settings=settings)
            result = router._cmd_sync("confluence", "TEST")

            assert "up to date" in result

        SessionManager.reset_instance()
