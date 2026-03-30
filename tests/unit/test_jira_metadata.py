"""Tests for Jira status/assignee metadata and activity query injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from metatron.connectors.jira_processing import process_jira_issue
from metatron.retrieval.search import _ACTIVITY_KW, _PERSON_EN, _PERSON_RU


def _make_jira_issue(**overrides):
    """Create a minimal Jira API issue dict."""
    fields = {
        "summary": "Test issue",
        "status": {"name": "In Progress"},
        "assignee": {"displayName": "Evgeny Petrov"},
        "reporter": {"displayName": "Admin"},
        "issuetype": {"name": "Task"},
        "priority": {"name": "High"},
        "description": "Test description",
        "comment": {"comments": []},
        "created": "2026-02-10T10:00:00.000+0000",
        "updated": "2026-02-11T10:00:00.000+0000",
    }
    fields.update(overrides)
    return {
        "key": "TEST-1",
        "fields": fields,
        "changelog": {"histories": []},
    }


class TestJiraStructuredData:
    def test_status_extracted(self) -> None:
        structured = process_jira_issue(_make_jira_issue())
        assert structured["status"] == "In Progress"

    def test_assignee_extracted(self) -> None:
        structured = process_jira_issue(_make_jira_issue())
        assert structured["assignee"] == "Evgeny Petrov"

    def test_no_assignee(self) -> None:
        structured = process_jira_issue(_make_jira_issue(assignee=None))
        assert structured["assignee"] is None


class TestActivityKeywordDetection:
    def test_english_activity_queries(self) -> None:
        queries = [
            "What is the team doing?",
            "Who is working on infrastructure?",
            "Show active tasks",
            "What's in progress?",
        ]
        for q in queries:
            assert any(kw in q.lower() for kw in _ACTIVITY_KW), f"Not detected: {q}"

    def test_russian_activity_queries(self) -> None:
        queries = [
            "Что делает команда?",
            "Кто работает над инфраструктурой?",
            "Чем занимается Женя?",
            "Покажи текущие задачи",
        ]
        for q in queries:
            assert any(kw in q.lower() for kw in _ACTIVITY_KW), f"Not detected: {q}"

    def test_non_activity_queries(self) -> None:
        queries = [
            "What is Metatron?",
            "Что такое RAG?",
            "Show me architecture docs",
            "Расскажи про аналитику",
        ]
        for q in queries:
            assert not any(kw in q.lower() for kw in _ACTIVITY_KW), f"False positive: {q}"


class TestPersonExtraction:
    def test_russian_pattern(self) -> None:
        m = _PERSON_RU.search("что делает женя")
        assert m and m.group(1) == "женя"

    def test_russian_pattern_works(self) -> None:
        m = _PERSON_RU.search("чем занимается сергей")
        assert m and m.group(1) == "сергей"

    def test_english_pattern_doing(self) -> None:
        m = _PERSON_EN.search("What is Evgeny doing")
        assert m
        assert m.group(1) == "Evgeny"

    def test_english_pattern_working(self) -> None:
        m = _PERSON_EN.search("what Konstantin is working on")
        assert m
        assert m.group(2) == "Konstantin"

    def test_no_person_in_generic_query(self) -> None:
        assert _PERSON_RU.search("что такое metatron") is None
        assert _PERSON_EN.search("what is metatron") is None


class TestPersonQuerySkipsGeneralInProgress:
    """Person-specific queries must NOT inject all In Progress tasks."""

    @patch("metatron.retrieval.channels.get_async_hybrid_store")
    @patch("metatron.retrieval.search.expand_query", side_effect=lambda q: q)
    @patch("metatron.retrieval.search.get_graph_entities", return_value=[])
    @patch("metatron.retrieval.search.chat_completion", return_value="Answer")
    async def test_person_detected_skips_status_search(
        self, mock_llm, mock_gents, mock_expand, mock_channels_store
    ) -> None:
        store_instance = AsyncMock()
        store_instance.search_by_status.return_value = []
        store_instance.search_by_assignee.return_value = [
            {"memory": "Task X", "data": "Task X", "title": "MTRNIX-10",
             "type": "jira", "score": 1.0, "payload": {}}
        ]
        store_instance.hybrid_search.return_value = []
        store_instance.scroll_by_title.return_value = []
        mock_channels_store.return_value = store_instance

        from metatron.retrieval.search import hybrid_search_and_answer
        await hybrid_search_and_answer(
            query="Что делает Женя?", intent_query="Что делает Женя?"
        )

        # search_by_assignee SHOULD have been called
        assert store_instance.search_by_assignee.called
        # search_by_status should NOT have been called (person takes priority)
        assert not store_instance.search_by_status.called

    @patch("metatron.retrieval.channels.get_async_hybrid_store")
    @patch("metatron.retrieval.search.expand_query", side_effect=lambda q: q)
    @patch("metatron.retrieval.search.get_graph_entities", return_value=[])
    @patch("metatron.retrieval.search.chat_completion", return_value="Answer")
    async def test_no_person_uses_status_search(
        self, mock_llm, mock_gents, mock_expand, mock_channels_store
    ) -> None:
        store_instance = AsyncMock()
        store_instance.search_by_status.return_value = [
            {"memory": "General task", "data": "General task", "title": "T-1",
             "type": "jira", "score": 1.0, "payload": {}}
        ]
        store_instance.hybrid_search.return_value = []
        store_instance.scroll_by_title.return_value = []
        mock_channels_store.return_value = store_instance

        from metatron.retrieval.search import hybrid_search_and_answer
        await hybrid_search_and_answer(
            query="What is the team doing?", intent_query="What is the team doing?"
        )

        # No person detected → general In Progress injection should run
        assert store_instance.search_by_status.called
        # search_by_assignee should NOT have been called
        assert not store_instance.search_by_assignee.called
