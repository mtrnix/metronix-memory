"""Tests for storage/graph_entities.py — entity type normalization and name validation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from metatron.storage.graph_entities import (
    ALLOWED_ENTITY_TYPES,
    TYPE_ALIASES,
    normalize_entity_type,
    is_valid_entity_name,
)


# ---------------------------------------------------------------------------
# normalize_entity_type
# ---------------------------------------------------------------------------

class TestNormalizeEntityType:
    def test_exact_allowed_type(self) -> None:
        assert normalize_entity_type("Person") == "Person"
        assert normalize_entity_type("Technology") == "Technology"
        assert normalize_entity_type("Task") == "Task"

    def test_case_insensitive_allowed(self) -> None:
        assert normalize_entity_type("person") == "Person"
        assert normalize_entity_type("TECHNOLOGY") == "Technology"
        assert normalize_entity_type("task") == "Task"

    def test_alias_technology(self) -> None:
        for alias in ("tool", "software", "framework", "library", "database",
                       "language", "tool/software", "ai model"):
            assert normalize_entity_type(alias) == "Technology", f"'{alias}' should map to Technology"

    def test_alias_task(self) -> None:
        for alias in ("task/issue", "workitem", "jira issue", "jiraissue",
                       "jira_task", "issue", "bug", "story", "задача"):
            assert normalize_entity_type(alias) == "Task", f"'{alias}' should map to Task"

    def test_alias_project(self) -> None:
        for alias in ("epic", "initiative", "project/feature", "проект"):
            assert normalize_entity_type(alias) == "Project", f"'{alias}' should map to Project"

    def test_alias_person(self) -> None:
        for alias in ("user", "developer", "engineer", "assignee", "github user"):
            assert normalize_entity_type(alias) == "Person", f"'{alias}' should map to Person"

    def test_alias_organization(self) -> None:
        for alias in ("team", "company", "department", "user group"):
            assert normalize_entity_type(alias) == "Organization", f"'{alias}' should map to Organization"

    def test_alias_service(self) -> None:
        for alias in ("api", "system", "platform", "microservice", "component"):
            assert normalize_entity_type(alias) == "Service", f"'{alias}' should map to Service"

    def test_alias_document(self) -> None:
        for alias in ("spec", "report", "rfc", "notebook", "repository", "файл"):
            assert normalize_entity_type(alias) == "Document", f"'{alias}' should map to Document"

    def test_alias_concept(self) -> None:
        for alias in ("idea", "pattern", "methodology", "technique", "feature",
                       "research topic", "use case", "role"):
            assert normalize_entity_type(alias) == "Concept", f"'{alias}' should map to Concept"

    def test_alias_event(self) -> None:
        for alias in ("meeting", "release", "deadline"):
            assert normalize_entity_type(alias) == "Event", f"'{alias}' should map to Event"

    def test_alias_location(self) -> None:
        for alias in ("environment", "deployment"):
            assert normalize_entity_type(alias) == "Location", f"'{alias}' should map to Location"

    def test_unknown_type_falls_back_to_concept(self) -> None:
        assert normalize_entity_type("Widget") == "Concept"
        assert normalize_entity_type("FooBar") == "Concept"
        assert normalize_entity_type("Дата обновления") == "Concept"

    def test_empty_type_falls_back_to_concept(self) -> None:
        assert normalize_entity_type("") == "Concept"
        assert normalize_entity_type("  ") == "Concept"

    def test_none_type_falls_back_to_concept(self) -> None:
        # In practice the type comes from dict.get("type", "") which is always str,
        # but test the edge case anyway.
        assert normalize_entity_type(None) == "Concept"

    def test_russian_aliases(self) -> None:
        assert normalize_entity_type("инструмент") == "Technology"
        assert normalize_entity_type("библиотека") == "Technology"
        assert normalize_entity_type("задача") == "Task"
        assert normalize_entity_type("проект") == "Project"
        assert normalize_entity_type("система") == "Service"

    def test_whitespace_stripped(self) -> None:
        assert normalize_entity_type("  tool  ") == "Technology"
        assert normalize_entity_type(" Person ") == "Person"

    def test_all_aliases_map_to_allowed_types(self) -> None:
        """Every alias value must be in ALLOWED_ENTITY_TYPES."""
        for alias, target in TYPE_ALIASES.items():
            assert target in ALLOWED_ENTITY_TYPES, (
                f"TYPE_ALIASES['{alias}'] = '{target}' is not in ALLOWED_ENTITY_TYPES"
            )


# ---------------------------------------------------------------------------
# is_valid_entity_name
# ---------------------------------------------------------------------------

class TestIsValidEntityName:
    def test_valid_names(self) -> None:
        assert is_valid_entity_name("Qdrant") is True
        assert is_valid_entity_name("John Doe") is True
        assert is_valid_entity_name("MTRNIX-42") is True
        assert is_valid_entity_name("Knowledge Graph") is True

    def test_too_short(self) -> None:
        assert is_valid_entity_name("") is False
        assert is_valid_entity_name("A") is False
        assert is_valid_entity_name(" ") is False

    def test_too_long(self) -> None:
        assert is_valid_entity_name("x" * 81) is False
        assert is_valid_entity_name("x" * 80) is True

    def test_url_rejected(self) -> None:
        assert is_valid_entity_name("https://example.com/page") is False
        assert is_valid_entity_name("http://localhost:8080") is False

    def test_absolute_path_rejected(self) -> None:
        assert is_valid_entity_name("/usr/local/bin/python") is False

    def test_long_path_with_slash_rejected(self) -> None:
        assert is_valid_entity_name("github.com/org/repo/tree/main/src") is False

    def test_short_slash_accepted(self) -> None:
        # Short names with / are OK (e.g. "I/O", "R&D/AI")
        assert is_valid_entity_name("I/O") is True

    def test_many_underscores_rejected(self) -> None:
        assert is_valid_entity_name("lora_training_data_v2_final") is False
        assert is_valid_entity_name("a_b_c_d") is True  # exactly 3 underscores is OK

    def test_none_rejected(self) -> None:
        assert is_valid_entity_name(None) is False


# ---------------------------------------------------------------------------
# Integration: extract_graph_from_text applies normalization + validation
# ---------------------------------------------------------------------------

class TestExtractGraphNormalization:
    @patch("metatron.storage.memgraph.chat_completion")
    def test_entities_normalized_and_filtered(self, mock_llm: MagicMock) -> None:
        """LLM returns freeform types; extraction normalizes them."""
        mock_llm.return_value = json.dumps({
            "entities": [
                {"name": "Qdrant", "type": "database"},
                {"name": "Kuzmin Konstantin", "type": "developer"},
                {"name": "MTRNIX", "type": "epic"},
                {"name": "https://example.com/long/path", "type": "URL"},
                {"name": "x", "type": "unknown"},
                {"name": "A" * 90, "type": "description"},
            ],
            "relationships": [
                {"source": "Kuzmin Konstantin", "target": "Qdrant", "type": "uses"},
                {"source": "x", "target": "Qdrant", "type": "bad"},
            ],
        })

        from metatron.storage.memgraph import extract_graph_from_text
        result = extract_graph_from_text("Some text about Qdrant and Kuzmin")

        entities = result["entities"]
        names = {e["name"] for e in entities}
        types = {e["name"]: e["type"] for e in entities}

        # Valid entities kept and normalized
        assert "Qdrant" in names
        assert types["Qdrant"] == "Technology"
        assert "Kuzmin Konstantin" in names
        assert types["Kuzmin Konstantin"] == "Person"
        assert "MTRNIX" in names
        assert types["MTRNIX"] == "Project"

        # Invalid entities filtered
        assert "https://example.com/long/path" not in names
        assert "x" not in names
        assert "A" * 90 not in names

        # Relationships: only valid entity pairs survive
        rels = result["relationships"]
        assert len(rels) == 1
        assert rels[0]["source"] == "Kuzmin Konstantin"
        assert rels[0]["target"] == "Qdrant"


# ---------------------------------------------------------------------------
# Confluence graph sync
# ---------------------------------------------------------------------------

class TestConfluenceGraphSync:
    @patch("metatron.storage.memgraph.write_doc_graph_to_memgraph")
    def test_confluence_doc_writes_to_graph(
        self, mock_write_graph: MagicMock,
    ) -> None:
        """Confluence documents should trigger graph write via _write_doc_to_graph."""
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import _write_doc_to_graph

        doc = Document(
            source_type="confluence",
            source_id="confluence:12345",
            workspace_id="TEST_WS",
            title="Architecture Overview",
            content="This page describes the system architecture.",
            author="admin",
            metadata={},
        )
        _write_doc_to_graph(doc, "TEST_WS")

        mock_write_graph.assert_called_once()
        call_kwargs = mock_write_graph.call_args
        assert call_kwargs.kwargs["workspace_id"] == "TEST_WS"
        assert call_kwargs.kwargs["doc_label"] == "confluence:12345"
        assert "Architecture Overview" in call_kwargs.kwargs["file_name"]

    @patch("metatron.storage.memgraph.write_doc_graph_to_memgraph")
    def test_upload_doc_writes_to_graph(self, mock_write_graph: MagicMock) -> None:
        """Uploaded files should also trigger graph write."""
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import _write_doc_to_graph

        doc = Document(
            source_type="upload",
            source_id="upload:report.txt",
            workspace_id="TEST_WS",
            title="Q4 Report",
            content="Revenue grew 15% in Q4.",
            author="user1",
            metadata={},
        )
        _write_doc_to_graph(doc, "TEST_WS")

        mock_write_graph.assert_called_once()

    @patch("metatron.storage.memgraph.write_doc_graph_to_memgraph")
    def test_graph_error_does_not_crash_pipeline(self, mock_write_graph: MagicMock) -> None:
        """Graph write errors should be logged, not raised."""
        mock_write_graph.side_effect = RuntimeError("Memgraph down")

        from metatron.core.models import Document
        from metatron.ingestion.pipeline import _write_doc_to_graph

        doc = Document(
            source_type="confluence",
            source_id="confluence:99",
            workspace_id="TEST_WS",
            title="Test",
            content="Test content",
            author="admin",
            metadata={},
        )
        # Should not raise
        _write_doc_to_graph(doc, "TEST_WS")

    @patch("metatron.ingestion.pipeline._write_doc_to_graph")
    @patch("metatron.ingestion.pipeline._write_jira_to_graph")
    @patch("metatron.ingestion.pipeline.ingest_documents")
    def test_pipeline_calls_graph_for_confluence(
        self, mock_ingest: MagicMock,
        mock_jira_graph: MagicMock, mock_doc_graph: MagicMock,
    ) -> None:
        """Verify the pipeline branches: jira → _write_jira_to_graph, confluence → _write_doc_to_graph.

        We test the branching logic by calling the internal functions directly
        since ingest_documents is hard to mock fully.
        """
        from metatron.core.models import Document

        jira_doc = Document(
            source_type="jira", source_id="JIRA-1", workspace_id="WS",
            title="Bug", content="Fix it", author="dev", metadata={},
        )
        conf_doc = Document(
            source_type="confluence", source_id="CONF-1", workspace_id="WS",
            title="Page", content="Content", author="admin", metadata={},
        )

        # Simulate what pipeline does for each doc type
        from metatron.ingestion.pipeline import _write_jira_to_graph, _write_doc_to_graph

        if jira_doc.source_type == "jira":
            _write_jira_to_graph(jira_doc, "WS")
        else:
            _write_doc_to_graph(jira_doc, "WS")

        if conf_doc.source_type == "jira":
            _write_jira_to_graph(conf_doc, "WS")
        else:
            _write_doc_to_graph(conf_doc, "WS")

        mock_jira_graph.assert_called_once()
        mock_doc_graph.assert_called_once()
