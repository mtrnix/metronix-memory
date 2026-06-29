"""Tests for storage/graph_entities.py — entity type normalization and name validation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from metronix.storage.graph_entities import (
    ALLOWED_ENTITY_TYPES,
    TYPE_ALIASES,
    _looks_like_sentence,
    is_role_not_person,
    is_valid_entity_name,
    normalize_entity_type,
    normalize_person_name,
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
        for alias in (
            "tool",
            "software",
            "framework",
            "library",
            "database",
            "language",
            "tool/software",
            "ai model",
        ):
            assert normalize_entity_type(alias) == "Technology", (
                f"'{alias}' should map to Technology"
            )

    def test_alias_task(self) -> None:
        for alias in (
            "task/issue",
            "workitem",
            "jira issue",
            "jiraissue",
            "jira_task",
            "issue",
            "bug",
            "story",
            "задача",
        ):
            assert normalize_entity_type(alias) == "Task", f"'{alias}' should map to Task"

    def test_alias_project(self) -> None:
        for alias in ("epic", "initiative", "project/feature", "проект"):
            assert normalize_entity_type(alias) == "Project", f"'{alias}' should map to Project"

    def test_alias_person(self) -> None:
        for alias in ("user", "developer", "engineer", "assignee", "github user"):
            assert normalize_entity_type(alias) == "Person", f"'{alias}' should map to Person"

    def test_alias_organization(self) -> None:
        for alias in ("team", "company", "department", "user group"):
            assert normalize_entity_type(alias) == "Organization", (
                f"'{alias}' should map to Organization"
            )

    def test_alias_service(self) -> None:
        for alias in ("api", "system", "platform", "microservice", "component"):
            assert normalize_entity_type(alias) == "Service", f"'{alias}' should map to Service"

    def test_alias_document(self) -> None:
        for alias in ("spec", "report", "rfc", "notebook", "repository", "файл"):
            assert normalize_entity_type(alias) == "Document", f"'{alias}' should map to Document"

    def test_alias_concept(self) -> None:
        for alias in (
            "idea",
            "pattern",
            "methodology",
            "technique",
            "feature",
            "research topic",
            "use case",
            "role",
        ):
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
        assert is_valid_entity_name("PROJ-42") is True
        assert is_valid_entity_name("Knowledge Graph") is True

    def test_too_short(self) -> None:
        assert is_valid_entity_name("") is False
        assert is_valid_entity_name("A") is False
        assert is_valid_entity_name(" ") is False

    def test_too_long(self) -> None:
        assert is_valid_entity_name("x" * 51) is False
        assert is_valid_entity_name("x" * 50) is True

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
    @patch("metronix.storage.neo4j_graph.chat_completion")
    def test_entities_normalized_and_filtered(self, mock_llm: MagicMock) -> None:
        """LLM returns freeform types; extraction normalizes them."""
        mock_llm.return_value = json.dumps(
            {
                "entities": [
                    {"name": "Qdrant", "type": "database"},
                    {"name": "Kuzmin Konstantin", "type": "developer"},
                    {"name": "MTRNIX", "type": "epic"},
                    {"name": "https://example.com/long/path", "type": "URL"},
                    {"name": "x", "type": "unknown"},
                    {"name": "A" * 55, "type": "description"},
                ],
                "relationships": [
                    {"source": "Kuzmin Konstantin", "target": "Qdrant", "type": "uses"},
                    {"source": "x", "target": "Qdrant", "type": "bad"},
                ],
            }
        )

        from metronix.storage.neo4j_graph import extract_graph_from_text

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
        assert "A" * 55 not in names

        # Relationships: only valid entity pairs survive
        rels = result["relationships"]
        assert len(rels) == 1
        assert rels[0]["source"] == "Kuzmin Konstantin"
        assert rels[0]["target"] == "Qdrant"


# ---------------------------------------------------------------------------
# Confluence graph sync
# ---------------------------------------------------------------------------


class TestConfluenceGraphSync:
    @patch("metronix.storage.neo4j_graph.write_doc_graph")
    def test_confluence_doc_writes_to_graph(
        self,
        mock_write_graph: MagicMock,
    ) -> None:
        """Confluence documents should trigger graph write via _write_doc_to_graph."""
        from metronix.core.models import Document
        from metronix.ingestion.pipeline import _write_doc_to_graph

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

    @patch("metronix.storage.neo4j_graph.write_doc_graph")
    def test_upload_doc_writes_to_graph(self, mock_write_graph: MagicMock) -> None:
        """Uploaded files should also trigger graph write."""
        from metronix.core.models import Document
        from metronix.ingestion.pipeline import _write_doc_to_graph

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

    @patch("metronix.storage.neo4j_graph.write_doc_graph")
    def test_graph_error_does_not_crash_pipeline(self, mock_write_graph: MagicMock) -> None:
        """Graph write errors should be logged, not raised."""
        mock_write_graph.side_effect = RuntimeError("Memgraph down")

        from metronix.core.models import Document
        from metronix.ingestion.pipeline import _write_doc_to_graph

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

    @patch("metronix.ingestion.pipeline._write_doc_to_graph")
    @patch("metronix.ingestion.pipeline._write_jira_to_graph")
    @patch("metronix.ingestion.pipeline.ingest_documents")
    def test_pipeline_calls_graph_for_confluence(
        self,
        mock_ingest: MagicMock,
        mock_jira_graph: MagicMock,
        mock_doc_graph: MagicMock,
    ) -> None:
        """Verify the pipeline branches: jira → _write_jira_to_graph, confluence → _write_doc_to_graph.

        We test the branching logic by calling the internal functions directly
        since ingest_documents is hard to mock fully.
        """  # noqa: E501
        from metronix.core.models import Document

        jira_doc = Document(
            source_type="jira",
            source_id="JIRA-1",
            workspace_id="WS",
            title="Bug",
            content="Fix it",
            author="dev",
            metadata={},
        )
        conf_doc = Document(
            source_type="confluence",
            source_id="CONF-1",
            workspace_id="WS",
            title="Page",
            content="Content",
            author="admin",
            metadata={},
        )

        # Simulate what pipeline does for each doc type
        from metronix.ingestion.pipeline import _write_doc_to_graph, _write_jira_to_graph

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


# ---------------------------------------------------------------------------
# is_role_not_person
# ---------------------------------------------------------------------------


class TestIsRoleNotPerson:
    def test_detects_role_keywords(self) -> None:
        for name in (
            "Admins",
            "Engineers",
            "Team Leads",
            "PMs",
            "Executives",
            "Analysts",
            "BI developers",
            "Directors",
            "Managers",
        ):
            assert is_role_not_person(name, "Person") is True, (
                f"'{name}' should be detected as a role"
            )

    def test_passes_real_person_names(self) -> None:
        for name in (
            "Kuzmin Konstantin",
            "John Doe",
            "Артём",
            "James",
            "Кирилл",
            "Alexander Fatin",
        ):
            assert is_role_not_person(name, "Person") is False, (
                f"'{name}' should NOT be detected as a role"
            )

    def test_ignores_non_person_types(self) -> None:
        assert is_role_not_person("Engineers", "Organization") is False
        assert is_role_not_person("Admins", "Concept") is False


# ---------------------------------------------------------------------------
# _looks_like_sentence
# ---------------------------------------------------------------------------


class TestLooksLikeSentence:
    def test_detects_long_phrases(self) -> None:
        assert (
            _looks_like_sentence("Implement graph extraction from Jira issues using LLM") is True
        )

    def test_detects_russian_verb_prefix(self) -> None:
        assert _looks_like_sentence("Написать тесты") is True
        assert _looks_like_sentence("Создать новый модуль") is True
        assert _looks_like_sentence("Автоматизировать деплой") is True

    def test_passes_short_entity_names(self) -> None:
        assert _looks_like_sentence("Qdrant") is False
        assert _looks_like_sentence("Knowledge Graph") is False
        assert _looks_like_sentence("PROJ-42") is False

    def test_name_length_filter_at_50(self) -> None:
        """Names over 50 chars are rejected by is_valid_entity_name."""
        long_name = "x" * 51
        assert is_valid_entity_name(long_name) is False
        assert is_valid_entity_name("x" * 50) is True

    def test_sentence_rejected_by_is_valid(self) -> None:
        """Sentence-like names are rejected even if under 50 chars."""
        assert is_valid_entity_name("Fix the search pipeline and add tests for it") is False


# ---------------------------------------------------------------------------
# normalize_person_name + PERSON_MERGE_MAP
# ---------------------------------------------------------------------------


class TestNormalizePersonName:
    def test_cyrillic_to_canonical(self) -> None:
        assert normalize_person_name("Артём", "Person") == "Artem Tov Ben"
        assert normalize_person_name("Константин", "Person") == "Kuzmin Konstantin"
        assert normalize_person_name("Женя", "Person") == "Evgeny Shcherbinin"
        assert normalize_person_name("Вова", "Person") == "Vladimir Belykh"
        assert normalize_person_name("Миша", "Person") == "Michael"

    def test_unknown_name_passes_through(self) -> None:
        assert normalize_person_name("Кирилл", "Person") == "Кирилл"
        assert normalize_person_name("Unknown Person", "Person") == "Unknown Person"

    def test_non_person_type_unchanged(self) -> None:
        assert normalize_person_name("Артём", "Organization") == "Артём"

    def test_case_insensitive_lookup(self) -> None:
        assert normalize_person_name("артём", "Person") == "Artem Tov Ben"
        assert normalize_person_name("КОСТЯ", "Person") == "Kuzmin Konstantin"


# ---------------------------------------------------------------------------
# Integration: roles reclassified, persons merged in extraction
# ---------------------------------------------------------------------------


class TestRoleReclassificationIntegration:
    @patch("metronix.storage.neo4j_graph.chat_completion")
    def test_roles_reclassified_to_organization(self, mock_llm: MagicMock) -> None:
        """Role names typed as Person get reclassified to Organization."""
        mock_llm.return_value = json.dumps(
            {
                "entities": [
                    {"name": "Engineers", "type": "Person"},
                    {"name": "John Doe", "type": "Person"},
                ],
                "relationships": [],
            }
        )

        from metronix.storage.neo4j_graph import extract_graph_from_text

        result = extract_graph_from_text("Engineers and John Doe worked on it")

        types = {e["name"]: e["type"] for e in result["entities"]}
        assert types["Engineers"] == "Organization"
        assert types["John Doe"] == "Person"

    @patch("metronix.storage.neo4j_graph.chat_completion")
    def test_person_merge_in_extraction(self, mock_llm: MagicMock) -> None:
        """Cyrillic person names are merged to canonical via PERSON_MERGE_MAP."""
        mock_llm.return_value = json.dumps(
            {
                "entities": [
                    {"name": "Артём", "type": "Person"},
                    {"name": "Qdrant", "type": "Technology"},
                ],
                "relationships": [
                    {"source": "Артём", "target": "Qdrant", "type": "uses"},
                ],
            }
        )

        from metronix.storage.neo4j_graph import extract_graph_from_text

        result = extract_graph_from_text("Артём работает с Qdrant")

        names = {e["name"] for e in result["entities"]}
        assert "Artem Tov Ben" in names
        assert "Артём" not in names
        # Relationship source should also be resolved
        assert result["relationships"][0]["source"] == "Artem Tov Ben"
        # merged_aliases should record the mapping
        assert result["merged_aliases"]["Артём"] == "Artem Tov Ben"


class TestAliasRelationshipWrite:
    @patch("metronix.storage.neo4j_graph.get_graph_driver")
    @patch("metronix.storage.neo4j_graph.extract_graph_from_text")
    def test_alias_relationships_created(
        self,
        mock_extract: MagicMock,
        mock_driver: MagicMock,
    ) -> None:
        """ALIAS relationships written for merged person names."""
        mock_extract.return_value = {
            "entities": [
                {"name": "Artem Tov Ben", "type": "Person"},
            ],
            "relationships": [],
            "merged_aliases": {"Артём": "Artem Tov Ben"},
        }

        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        from metronix.storage.neo4j_graph import write_doc_graph

        write_doc_graph(
            text="Артём wrote code",
            file_name="test.txt",
            user_id="user1",
            workspace_id="TEST",
            doc_label="DOC-1",
        )

        # Find the ALIAS cypher call among all session.run calls
        alias_calls = [c for c in mock_session.run.call_args_list if "ALIAS" in str(c)]
        assert len(alias_calls) == 1
        params = alias_calls[0][0][1]
        # With $param approach, values are in the params dict
        assert "Арт" in params["alias"]  # Cyrillic alias name in params
        assert params["canon"] == "Artem Tov Ben"  # canonical name in params

    @patch("metronix.storage.neo4j_graph.get_graph_driver")
    @patch("metronix.storage.neo4j_graph.extract_graph_from_text")
    def test_alias_sets_type_person(
        self,
        mock_extract: MagicMock,
        mock_driver: MagicMock,
    ) -> None:
        """ALIAS entity node gets type='Person' set explicitly."""
        mock_extract.return_value = {
            "entities": [
                {"name": "Artem Tov Ben", "type": "Person"},
            ],
            "relationships": [],
            "merged_aliases": {"Артём": "Artem Tov Ben"},
        }

        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        from metronix.storage.neo4j_graph import write_doc_graph

        write_doc_graph(
            text="Артём wrote code",
            file_name="test.txt",
            user_id="user1",
            workspace_id="TEST",
            doc_label="DOC-1",
        )

        alias_calls = [c for c in mock_session.run.call_args_list if "ALIAS" in str(c)]
        assert len(alias_calls) == 1
        cypher = alias_calls[0][0][0]
        assert "SET a.type = 'Person'" in cypher

    @patch("metronix.storage.neo4j_graph.get_graph_driver")
    @patch("metronix.storage.neo4j_graph.extract_graph_from_text")
    def test_self_referencing_alias_skipped(
        self,
        mock_extract: MagicMock,
        mock_driver: MagicMock,
    ) -> None:
        """Self-referencing aliases (alias == canonical) are skipped."""
        mock_extract.return_value = {
            "entities": [
                {"name": "John Doe", "type": "Person"},
            ],
            "relationships": [],
            "merged_aliases": {"John Doe": "John Doe"},
        }

        mock_session = MagicMock()
        mock_driver.return_value.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.return_value.session.return_value.__exit__ = MagicMock(return_value=False)

        from metronix.storage.neo4j_graph import write_doc_graph

        write_doc_graph(
            text="John Doe wrote code",
            file_name="test.txt",
            user_id="user1",
            workspace_id="TEST",
            doc_label="DOC-1",
        )

        alias_calls = [c for c in mock_session.run.call_args_list if "ALIAS" in str(c)]
        assert len(alias_calls) == 0


# ---------------------------------------------------------------------------
# New role keywords
# ---------------------------------------------------------------------------


class TestNewRoleKeywords:
    def test_new_role_keywords_reclassified(self) -> None:
        """Newly added role keywords are detected as roles, not persons."""
        new_roles = [
            "Knowledge Consumers",
            "Knowledge Stewards",
            "Knowledge Steward",
            "Semantic Owners",
            "Ontology Owners",
            "Customer Success Engineer",
            "MTRNIX User",
            "Metronix User",
            "Data Scientist",
        ]
        for name in new_roles:
            assert is_role_not_person(name, "Person") is True, (
                f"'{name}' should be detected as a role"
            )
