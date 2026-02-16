"""Tests for temporal facts — time-bounded relationships in Memgraph.

Covers:
- resolutiondate extraction from Jira
- Temporal metadata in Jira connector
- Pipeline threading of dates to graph writers
- Temporal properties on Jira and document edges
- Temporal query filtering in graph_ops
"""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch, call

from metatron.connectors.jira_processing import process_jira_issue
from metatron.core.models import Document


def _make_jira_fields(**overrides: object) -> dict:
    """Build a minimal Jira API issue dict."""
    fields = {
        "summary": "Test task",
        "status": {"name": "In Progress"},
        "assignee": {"displayName": "Alice", "emailAddress": "alice@test.com"},
        "reporter": {"displayName": "Bob", "emailAddress": "bob@test.com"},
        "created": "2025-06-01T10:00:00.000+0000",
        "updated": "2025-06-15T12:00:00.000+0000",
        "priority": {"name": "High"},
        "issuetype": {"name": "Task"},
        "description": "Some work",
        "comment": {"comments": []},
    }
    fields.update(overrides)
    return {"id": "10001", "key": "TEST-1", "fields": fields, "changelog": {"histories": []}}


# --- 1. resolutiondate extracted from Jira fields ---

class TestResolutiondateExtraction:
    def test_resolutiondate_extracted(self) -> None:
        issue = _make_jira_fields(resolutiondate="2025-06-20T09:00:00.000+0000")
        result = process_jira_issue(issue)
        assert result["resolutiondate"] == "2025-06-20T09:00:00.000+0000"

    def test_resolutiondate_none_when_unresolved(self) -> None:
        issue = _make_jira_fields()  # no resolutiondate field
        result = process_jira_issue(issue)
        assert result["resolutiondate"] is None


# --- 3. Jira connector metadata includes temporal strings ---

class TestJiraConnectorMetadata:
    def test_metadata_includes_temporal_strings(self) -> None:
        from metatron.connectors.jira import JiraConnector

        connector = JiraConnector()
        raw_issue = _make_jira_fields(resolutiondate="2025-06-20T09:00:00.000+0000")
        doc = connector._issue_to_document(raw_issue, "ws1")

        assert doc.metadata["created_at_str"] == "2025-06-01T10:00:00.000+0000"
        assert doc.metadata["updated_at_str"] == "2025-06-15T12:00:00.000+0000"
        assert doc.metadata["resolved_at_str"] == "2025-06-20T09:00:00.000+0000"

    def test_metadata_empty_strings_when_unresolved(self) -> None:
        from metatron.connectors.jira import JiraConnector

        connector = JiraConnector()
        raw_issue = _make_jira_fields()
        doc = connector._issue_to_document(raw_issue, "ws1")

        assert doc.metadata["resolved_at_str"] == ""


# --- 4. Pipeline passes temporal data to graph writers ---

class TestPipelineTemporalData:
    @patch("metatron.storage.graph_jira.write_jira_graph_to_memgraph")
    def test_write_jira_to_graph_passes_temporal_data(self, mock_write: MagicMock) -> None:
        from metatron.ingestion.pipeline import _write_jira_to_graph

        doc = Document(
            source_type="jira",
            source_id="TEST-1",
            workspace_id="ws1",
            title="[TEST-1] Test task",
            content="# [TEST-1] Test task\n\n**Status:** Done",
            author="Bob",
            metadata={
                "status": "Done",
                "assignee": "Alice",
                "reporter": "Bob",
                "issuetype": "Task",
                "priority": "High",
                "created_at_str": "2025-06-01T10:00:00.000+0000",
                "updated_at_str": "2025-06-15T12:00:00.000+0000",
                "resolved_at_str": "2025-06-20T09:00:00.000+0000",
            },
        )
        _write_jira_to_graph(doc, "ws1")

        mock_write.assert_called_once()
        jira_data = mock_write.call_args[0][0]
        assert jira_data["created"] == "2025-06-01T10:00:00.000+0000"
        assert jira_data["updated"] == "2025-06-15T12:00:00.000+0000"
        assert jira_data["resolved_at"] == "2025-06-20T09:00:00.000+0000"


# --- 5-6. _link_person sets valid_from/valid_to ---

class TestLinkPersonTemporal:
    def test_assigned_to_resolved_task_has_valid_to(self) -> None:
        from metatron.storage.graph_jira import _link_person

        mock_session = MagicMock()
        _link_person(
            mock_session, "Alice", "TEST-1", "ASSIGNED_TO", "ws1", "user", "dl",
            valid_from="2025-06-01", valid_to="2025-06-20",
        )
        mock_session.run.assert_called_once()
        params = mock_session.run.call_args[0][1]
        assert params["vf"] == "2025-06-01"
        assert params["vt"] == "2025-06-20"
        assert "r.valid_from = $vf" in mock_session.run.call_args[0][0]
        assert "r.valid_to = $vt" in mock_session.run.call_args[0][0]

    def test_reported_has_null_valid_to(self) -> None:
        from metatron.storage.graph_jira import _link_person

        mock_session = MagicMock()
        _link_person(
            mock_session, "Bob", "TEST-1", "REPORTED", "ws1", "user", "dl",
            valid_from="2025-06-01", valid_to=None,
        )
        mock_session.run.assert_called_once()
        params = mock_session.run.call_args[0][1]
        assert params["vf"] == "2025-06-01"
        assert params["vt"] is None


# --- 7. Document edges get valid_from from doc_date ---

class TestDocumentEdgesTemporal:
    @patch("metatron.storage.memgraph.extract_graph_from_text")
    @patch("metatron.storage.memgraph.get_memgraph_driver")
    def test_document_edges_get_valid_from(
        self, mock_driver: MagicMock, mock_extract: MagicMock,
    ) -> None:
        from metatron.storage.memgraph import write_doc_graph_to_memgraph

        mock_extract.return_value = {
            "entities": [{"name": "Qdrant", "type": "Technology"}],
            "relationships": [],
        }
        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        write_doc_graph_to_memgraph(
            text="Qdrant is great",
            file_name="test.md",
            workspace_id="ws1",
            doc_label="ws1:test.md",
            upload_time="2025-07-01T00:00:00",
            doc_date="2025-06-15",
        )

        # UPLOADED edge should use upload_time as valid_from
        uploaded_call = mock_session.run.call_args_list[0]
        assert "r.valid_from = $vf" in uploaded_call[0][0]
        assert uploaded_call[0][1]["vf"] == "2025-07-01T00:00:00"

        # MENTIONS edge should use doc_date (edge_date) as valid_from
        mentions_call = mock_session.run.call_args_list[1]
        assert "r.valid_from = $vf" in mentions_call[0][0]
        assert mentions_call[0][1]["vf"] == "2025-06-15"


# --- 8-9. get_graph_relationships active_only filter ---

class TestGraphRelationshipsTemporal:
    @patch("metatron.storage.graph_ops.get_memgraph_driver")
    def test_active_only_adds_valid_to_filter(self, mock_driver: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session.run.return_value = []
        mock_driver.return_value.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        from metatron.storage.graph_ops import get_graph_relationships
        get_graph_relationships(["Alice"], workspace_id="ws1", active_only=True)

        cypher = mock_session.run.call_args[0][0]
        assert "r.valid_to IS NULL" in cypher

    @patch("metatron.storage.graph_ops.get_memgraph_driver")
    def test_default_does_not_add_temporal_filter(self, mock_driver: MagicMock) -> None:
        mock_session = MagicMock()
        mock_session.run.return_value = []
        mock_driver.return_value.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        from metatron.storage.graph_ops import get_graph_relationships
        get_graph_relationships(["Alice"], workspace_id="ws1", active_only=False)

        cypher = mock_session.run.call_args[0][0]
        assert "valid_to IS NULL" not in cypher


# --- 10. Result dicts include valid_from/valid_to keys ---

class TestResultDictShape:
    @patch("metatron.storage.graph_ops.get_memgraph_driver")
    def test_result_dicts_include_temporal_keys(self, mock_driver: MagicMock) -> None:
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, k: {
            "source": "Alice",
            "target": "TEST-1",
            "rel_type": "works_on",
            "valid_from": "2025-06-01",
            "valid_to": None,
        }[k]

        mock_session = MagicMock()
        mock_session.run.return_value = [mock_record]
        mock_driver.return_value.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        from metatron.storage.graph_ops import get_graph_relationships
        results = get_graph_relationships(["Alice"], workspace_id="ws1")

        assert len(results) == 1
        assert results[0]["valid_from"] == "2025-06-01"
        assert results[0]["valid_to"] is None
        assert "source" in results[0]
        assert "target" in results[0]
        assert "type" in results[0]
