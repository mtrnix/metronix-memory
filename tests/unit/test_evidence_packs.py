# tests/unit/test_evidence_packs.py
"""Tests for structured evidence packs — source roles, marking, grouping, context assembly."""

from __future__ import annotations


class TestConnectorSourceRoles:
    """Verify each connector declares the correct source_role."""

    def test_connector_interface_default(self) -> None:
        from metatron.core.interfaces import ConnectorInterface
        assert ConnectorInterface.source_role == "knowledge_base"

    def test_jira_connector_role(self) -> None:
        from metatron.connectors.jira import JiraConnector
        assert JiraConnector.source_role == "task_tracker"

    def test_github_connector_role(self) -> None:
        from metatron.connectors.github import GitHubConnector
        assert GitHubConnector.source_role == "task_tracker"

    def test_slack_history_connector_role(self) -> None:
        from metatron.connectors.slack_history import SlackHistoryConnector
        assert SlackHistoryConnector.source_role == "communication"

    def test_files_connector_role(self) -> None:
        from metatron.connectors.files import FilesConnector
        assert FilesConnector.source_role == "user_upload"

    def test_confluence_connector_role(self) -> None:
        from metatron.connectors.confluence import ConfluenceConnector
        assert ConfluenceConnector.source_role == "knowledge_base"

    def test_notion_connector_role(self) -> None:
        from metatron.connectors.notion import NotionConnector
        assert NotionConnector.source_role == "knowledge_base"

    def test_gdrive_connector_role(self) -> None:
        from metatron.connectors.gdrive import GDriveConnector
        assert GDriveConnector.source_role == "knowledge_base"


class TestSourceRoleDataFlow:
    """Verify source_role flows through Document → pipeline → Qdrant payload."""

    def test_document_has_source_role_field(self) -> None:
        from metatron.core.models import Document
        doc = Document(title="test", source_role="task_tracker")
        assert doc.source_role == "task_tracker"

    def test_document_source_role_default_empty(self) -> None:
        from metatron.core.models import Document
        doc = Document(title="test")
        assert doc.source_role == ""

    def test_format_result_includes_source_role(self) -> None:
        """_format_result extracts source_role from Qdrant payload."""
        from unittest.mock import MagicMock
        from metatron.storage.qdrant import QdrantVectorStore

        store = QdrantVectorStore.__new__(QdrantVectorStore)
        point = MagicMock()
        point.payload = {
            "data": "some text",
            "title": "Test",
            "type": "jira",
            "source_role": "task_tracker",
            "url": "",
            "date": "",
            "doc_label": "jira:123",
            "workspace_id": "ws1",
        }
        point.id = "abc123"
        result = store._format_result(point, 0.95)
        assert result["source_role"] == "task_tracker"

    def test_format_result_source_role_defaults_to_knowledge_base(self) -> None:
        """Chunks indexed before reindex get default source_role."""
        from unittest.mock import MagicMock
        from metatron.storage.qdrant import QdrantVectorStore

        store = QdrantVectorStore.__new__(QdrantVectorStore)
        point = MagicMock()
        point.payload = {"data": "some text", "title": "Old"}
        point.id = "old123"
        result = store._format_result(point, 0.8)
        assert result["source_role"] == "knowledge_base"
