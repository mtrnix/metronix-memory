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


class TestSourceRoleInCallers:
    """Verify source_role is passed from both sync and upload callers."""

    def test_ingest_documents_accepts_source_role_param(self) -> None:
        """ingest_documents signature includes source_role."""
        import inspect

        from metatron.ingestion.pipeline import ingest_documents
        sig = inspect.signature(ingest_documents)
        assert "source_role" in sig.parameters
        assert sig.parameters["source_role"].default == "knowledge_base"

    def test_chat_upload_metadata_has_source_role(self) -> None:
        """_ingest_text metadata dict includes source_role for uploads."""
        import inspect

        from metatron.api.routes import chat
        source = inspect.getsource(chat._ingest_text)
        assert "source_role" in source
        assert "user_upload" in source


class TestCollectFragsDicts:
    """_collect_frags returns list[dict] with metadata."""

    def test_returns_list_of_dicts(self) -> None:
        from metatron.retrieval.search import _collect_frags

        base = [
            {
                "memory": "Some text about architecture",
                "data": "Some text about architecture",
                "title": "Architecture Overview",
                "type": "confluence",
                "source_role": "knowledge_base",
                "doc_label": "confluence:123",
                "date": "2026-03-20",
                "payload": {},
            },
        ]
        frags, seen, total, doc_stats = _collect_frags(base, set(), 0)
        assert len(frags) == 1
        assert isinstance(frags[0], dict)
        expected = "[CONFLUENCE] Architecture Overview\nSome text about architecture"
        assert frags[0]["text"] == expected
        assert frags[0]["source_type"] == "confluence"
        assert frags[0]["source_role"] == "knowledge_base"
        assert frags[0]["title"] == "Architecture Overview"
        assert frags[0]["date"] == "2026-03-20"
        assert frags[0]["doc_label"] == "confluence:123"

    def test_default_source_role_knowledge_base(self) -> None:
        """Fragments without source_role get default 'knowledge_base'."""
        from metatron.retrieval.search import _collect_frags

        base = [
            {
                "memory": "Old chunk without source_role",
                "data": "Old chunk without source_role",
                "title": "Old Doc",
                "type": "confluence",
                "doc_label": "c:1",
                "payload": {},
            },
        ]
        frags, _, _, _ = _collect_frags(base, set(), 0)
        assert frags[0]["source_role"] == "knowledge_base"

    def test_dedup_by_text_hash(self) -> None:
        """Duplicate fragments are deduplicated by hash of first 200 chars."""
        from metatron.retrieval.search import _collect_frags

        item = {
            "memory": "Same text",
            "data": "Same text",
            "title": "Doc",
            "type": "confluence",
            "source_role": "knowledge_base",
            "doc_label": "c:1",
            "payload": {},
        }
        frags, _, _, _ = _collect_frags([item, item], set(), 0)
        assert len(frags) == 1

    def test_doc_stats_still_tracked(self) -> None:
        """FinOps doc_stats tracking works with dict fragments."""
        from metatron.retrieval.search import _collect_frags

        base = [
            {
                "memory": "Task implementation details",
                "data": "Task implementation details",
                "title": "MTRNIX-104",
                "type": "jira",
                "source_role": "task_tracker",
                "doc_label": "jira:104",
                "payload": {},
            },
        ]
        frags, _, _, doc_stats = _collect_frags(base, set(), 0)
        assert "jira:104" in doc_stats
        assert doc_stats["jira:104"]["title"] == "MTRNIX-104"
        assert doc_stats["jira:104"]["fetch_count"] == 1


class TestTokenBudgetWithDicts:
    """select_fragments_within_budget works with list[dict] fragments."""

    def test_accepts_dict_fragments(self) -> None:
        from metatron.retrieval.token_budget import select_fragments_within_budget

        frags = [
            {"text": "Short fragment one.",
             "source_role": "task_tracker", "evidence_marker": "PRIMARY"},
            {"text": "Short fragment two.",
             "source_role": "knowledge_base", "evidence_marker": "SUPPORTING"},
        ]
        result = select_fragments_within_budget(frags, max_tokens=10000)
        assert len(result) == 2
        assert all(isinstance(f, dict) for f in result)
        assert result[0]["source_role"] == "task_tracker"

    def test_budget_truncation_preserves_metadata(self) -> None:
        from metatron.retrieval.token_budget import select_fragments_within_budget

        frags = [
            {"text": "A" * 4000, "source_role": "task_tracker", "evidence_marker": "PRIMARY"},
            {"text": "B" * 4000, "source_role": "knowledge_base", "evidence_marker": "SUPPORTING"},
            {"text": "C" * 4000, "source_role": "communication", "evidence_marker": "SUPPORTING"},
        ]
        # Budget of 2500 tokens ~ 10000 chars, should fit first 2 but not 3rd
        result = select_fragments_within_budget(frags, max_tokens=2500)
        assert len(result) <= 2
        assert all("source_role" in f for f in result)

    def test_backwards_compat_with_str_fragments(self) -> None:
        """Still works with list[str] for backward compatibility during migration."""
        from metatron.retrieval.token_budget import select_fragments_within_budget

        frags = ["Fragment one text.", "Fragment two text."]
        result = select_fragments_within_budget(frags, max_tokens=10000)
        assert len(result) == 2
        assert all(isinstance(f, str) for f in result)


class TestMarkEvidenceRole:
    """_mark_evidence_role labels fragments PRIMARY/SUPPORTING based on query profile."""

    def _make_frag(self, source_role: str) -> dict:
        return {
            "text": f"Fragment from {source_role}",
            "source_type": "test",
            "source_role": source_role,
            "title": "Test",
            "date": "",
            "doc_label": "t:1",
            "evidence_marker": "",
        }

    def test_execution_profile_primary_is_task_tracker(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "execution")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_documentation_profile_primary_is_knowledge_base(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "documentation")
        assert frags[0]["evidence_marker"] == "SUPPORTING"
        assert frags[1]["evidence_marker"] == "PRIMARY"

    def test_user_file_profile_primary_is_user_upload(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("user_upload"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "user_file")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_mixed_profile_all_supporting(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("knowledge_base")]
        _mark_evidence_role(frags, "mixed")
        assert all(f["evidence_marker"] == "SUPPORTING" for f in frags)

    def test_relationship_profile_primary_is_knowledge_base(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("knowledge_base"), self._make_frag("task_tracker")]
        _mark_evidence_role(frags, "relationship")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_temporal_profile_primary_is_task_tracker(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker"), self._make_frag("communication")]
        _mark_evidence_role(frags, "temporal")
        assert frags[0]["evidence_marker"] == "PRIMARY"
        assert frags[1]["evidence_marker"] == "SUPPORTING"

    def test_unknown_profile_all_supporting(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("task_tracker")]
        _mark_evidence_role(frags, "unknown_profile")
        assert frags[0]["evidence_marker"] == "SUPPORTING"

    def test_unknown_source_role_gets_supporting(self) -> None:
        from metatron.retrieval.search import _mark_evidence_role

        frags = [self._make_frag("some_new_connector")]
        _mark_evidence_role(frags, "execution")
        assert frags[0]["evidence_marker"] == "SUPPORTING"


class TestBuildCtxGrouped:
    """_build_ctx groups fragments by source_role with markdown sections."""

    def _make_frag(self, source_role: str, marker: str, source_type: str = "jira",
                   title: str = "Doc", date: str = "2026-03-25") -> dict:
        return {
            "text": f"[{source_type.upper()}] {title}\nContent from {source_role}",
            "source_type": source_type,
            "source_role": source_role,
            "title": title,
            "date": date,
            "doc_label": f"{source_type}:1",
            "evidence_marker": marker,
        }

    def test_primary_group_appears_first(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [
            self._make_frag("knowledge_base", "SUPPORTING", "confluence", "Arch Overview"),
            self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104"),
        ]
        ctx = _build_ctx("What is the team doing?", "en", frags, [], [], [])
        # Task tracker section (has PRIMARY) should appear before knowledge base
        tt_pos = ctx.find("## Task tracker sources")
        kb_pos = ctx.find("## Knowledge base sources")
        assert tt_pos < kb_pos
        assert "[PRIMARY]" in ctx
        assert "[SUPPORTING]" in ctx

    def test_empty_groups_skipped(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [
            self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104"),
        ]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "## Task tracker sources" in ctx
        assert "## Knowledge base sources" not in ctx
        assert "## Communication sources" not in ctx

    def test_all_supporting_no_primary_group(self) -> None:
        """When mixed profile (all SUPPORTING), groups appear in fixed order."""
        from metatron.retrieval.search import _build_ctx

        frags = [
            self._make_frag("knowledge_base", "SUPPORTING", "confluence", "Doc1"),
            self._make_frag("task_tracker", "SUPPORTING", "jira", "MTRNIX-99"),
        ]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        # Fixed order: knowledge_base before task_tracker
        kb_pos = ctx.find("## Knowledge base sources")
        tt_pos = ctx.find("## Task tracker sources")
        assert kb_pos < tt_pos

    def test_graph_context_preserved(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [self._make_frag("task_tracker", "PRIMARY", "jira", "J1")]
        g_ents = [{"name": "Metatron", "type": "System"}]
        g_rels = [{"source": "Metatron", "target": "RAG", "type": "uses"}]
        g_docs = ["doc:1"]
        ctx = _build_ctx("query", "en", frags, g_ents, g_rels, g_docs)
        assert "## Graph context" in ctx
        assert "Metatron" in ctx

    def test_date_in_fragment_header(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104", "2026-03-25")]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "(2026-03-25)" in ctx

    def test_fragment_without_date(self) -> None:
        from metatron.retrieval.search import _build_ctx

        frags = [self._make_frag("task_tracker", "PRIMARY", "jira", "MTRNIX-104", "")]
        ctx = _build_ctx("query", "en", frags, [], [], [])
        assert "()" not in ctx  # no empty parens


class TestSystemPromptEvidenceRules:
    """HYBRID_SYSTEM_PROMPT contains evidence rules and no deduplicated lines."""

    def test_evidence_rules_section_exists(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "## Evidence rules" in HYBRID_SYSTEM_PROMPT

    def test_primary_supporting_mentioned(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "[PRIMARY]" in HYBRID_SYSTEM_PROMPT
        assert "[SUPPORTING]" in HYBRID_SYSTEM_PROMPT

    def test_citation_rule_present(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "cite the source" in HYBRID_SYSTEM_PROMPT

    def test_contradiction_handling_present(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "contradict" in HYBRID_SYSTEM_PROMPT

    def test_insufficient_context_rule_present(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "insufficient" in HYBRID_SYSTEM_PROMPT

    def test_deduplicated_line_removed_invent_facts(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        removed = "Do not invent facts that are not in the provided fragments."
        assert removed not in HYBRID_SYSTEM_PROMPT

    def test_deduplicated_line_removed_primary_source(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "Use text fragments as the primary source of facts." not in HYBRID_SYSTEM_PROMPT

    def test_source_references_preserved(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "[$[" in HYBRID_SYSTEM_PROMPT

    def test_language_rules_preserved(self) -> None:
        from metatron.retrieval.prompts import HYBRID_SYSTEM_PROMPT
        assert "CRITICAL RULE: RESPONSE LANGUAGE" in HYBRID_SYSTEM_PROMPT


class TestEvidencePacksIntegration:
    """End-to-end test: marking + grouping + context assembly."""

    def test_full_pipeline_execution_profile(self) -> None:
        """Execution profile: task_tracker = PRIMARY, knowledge_base = SUPPORTING."""
        from metatron.retrieval.search import _build_ctx, _collect_frags, _mark_evidence_role

        base = [
            {
                "memory": "Implementing auth module, status: in progress",
                "data": "Implementing auth module, status: in progress",
                "title": "MTRNIX-104",
                "type": "jira",
                "source_role": "task_tracker",
                "doc_label": "jira:104",
                "date": "2026-03-25",
                "payload": {},
            },
            {
                "memory": "The system uses 6 architectural layers for separation of concerns",
                "data": "The system uses 6 architectural layers for separation of concerns",
                "title": "Architecture Overview",
                "type": "confluence",
                "source_role": "knowledge_base",
                "doc_label": "confluence:arch",
                "date": "2026-03-20",
                "payload": {},
            },
        ]

        frags, _, _, doc_stats = _collect_frags(base, set(), 0)
        assert len(frags) == 2
        assert all(isinstance(f, dict) for f in frags)

        _mark_evidence_role(frags, "execution")
        # Jira = task_tracker → PRIMARY for execution profile
        jira_frag = next(f for f in frags if f["source_type"] == "jira")
        conf_frag = next(f for f in frags if f["source_type"] == "confluence")
        assert jira_frag["evidence_marker"] == "PRIMARY"
        assert conf_frag["evidence_marker"] == "SUPPORTING"

        ctx = _build_ctx("What is the team doing?", "en", frags, [], [], [])
        # Task tracker section appears first (has PRIMARY)
        assert ctx.index("## Task tracker sources") < ctx.index("## Knowledge base sources")
        assert "[PRIMARY]" in ctx
        assert "[SUPPORTING]" in ctx
        assert "MTRNIX-104" in ctx
        assert "Architecture Overview" in ctx

    def test_full_pipeline_mixed_profile(self) -> None:
        """Mixed profile: all fragments SUPPORTING, fixed group order."""
        from metatron.retrieval.search import _build_ctx, _collect_frags, _mark_evidence_role

        base = [
            {
                "memory": "Some jira content",
                "data": "Some jira content",
                "title": "MTRNIX-99",
                "type": "jira",
                "source_role": "task_tracker",
                "doc_label": "jira:99",
                "payload": {},
            },
            {
                "memory": "Some confluence content",
                "data": "Some confluence content",
                "title": "Doc",
                "type": "confluence",
                "source_role": "knowledge_base",
                "doc_label": "confluence:1",
                "payload": {},
            },
        ]

        frags, _, _, _ = _collect_frags(base, set(), 0)
        _mark_evidence_role(frags, "mixed")

        assert all(f["evidence_marker"] == "SUPPORTING" for f in frags)

        ctx = _build_ctx("query", "en", frags, [], [], [])
        # No PRIMARY group → fixed order: knowledge_base before task_tracker
        kb_pos = ctx.find("## Knowledge base sources")
        tt_pos = ctx.find("## Task tracker sources")
        assert kb_pos < tt_pos

    def test_trace_format_with_dict_frags(self) -> None:
        """Trace logging calculations work with dict fragments."""
        frags = [
            {"text": "word1 word2 word3",
             "source_role": "task_tracker", "evidence_marker": "PRIMARY"},
            {"text": "word4 word5",
             "source_role": "knowledge_base", "evidence_marker": "SUPPORTING"},
        ]
        token_budget_used = sum(len(f["text"]) for f in frags) // 4
        source_word_count = sum(len(f["text"].split()) for f in frags)
        assert token_budget_used > 0
        assert source_word_count == 5
