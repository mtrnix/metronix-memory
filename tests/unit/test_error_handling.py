"""Tests for error handling — router, LLM retry, search pipeline degradation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from metronix.agent.router import AgentRouter
from metronix.agent.sessions import SessionManager
from metronix.llm import chat_completion_with_retry
from metronix.llm.base import LLMAuthenticationError, LLMConnectionError, LLMError


@pytest.fixture(autouse=True)
def _reset_sessions():
    SessionManager.reset_instance()
    yield
    SessionManager.reset_instance()


@pytest.fixture
def settings():
    s = MagicMock()
    s.default_workspace_id = "TEST_WS"
    s.llm_provider = "deepseek"
    s.llm_fallback_provider = ""
    return s


@pytest.fixture
def router(settings):
    return AgentRouter(settings=settings, sessions=SessionManager())


# ---------------------------------------------------------------------------
# Router error handling
# ---------------------------------------------------------------------------


class TestRouterErrors:
    @patch("metronix.agent.router.hybrid_search_and_answer_sync")
    def test_llm_error_returns_friendly_message(
        self,
        mock_search: MagicMock,
        router: AgentRouter,
    ) -> None:
        mock_search.side_effect = LLMError("provider timeout")
        result = router.route("query", user_id="u1")
        assert "AI service is temporarily unavailable" in result
        assert "provider timeout" not in result

    @patch("metronix.agent.router.hybrid_search_and_answer_sync")
    def test_qdrant_response_handling_error_returns_friendly_message(
        self,
        mock_search: MagicMock,
        router: AgentRouter,
    ) -> None:
        """Qdrant ResponseHandlingException triggers search-service message."""
        from qdrant_client.http.exceptions import ResponseHandlingException

        mock_search.side_effect = ResponseHandlingException("connection refused")
        result = router.route("query", user_id="u1")
        assert "Search service is temporarily unavailable" in result
        assert "connection refused" not in result

    @patch("metronix.agent.router.hybrid_search_and_answer_sync")
    def test_generic_error_returns_friendly_message(
        self,
        mock_search: MagicMock,
        router: AgentRouter,
    ) -> None:
        """Unexpected errors are caught by the generic handler."""
        mock_search.side_effect = RuntimeError("something unexpected")
        result = router.route("query", user_id="u1")
        assert "Something went wrong" in result
        assert "something unexpected" not in result

    @patch("metronix.agent.router.hybrid_search_and_answer_sync")
    def test_unexpected_error_hides_details(
        self,
        mock_search: MagicMock,
        router: AgentRouter,
    ) -> None:
        mock_search.side_effect = ValueError("secret internal detail")
        result = router.route("query", user_id="u1")
        assert "Something went wrong" in result
        assert "secret internal detail" not in result

    def test_sync_returns_api_redirect(
        self,
        router: AgentRouter,
    ) -> None:
        """Sync via chat now redirects to API."""
        result = router.route("/sync confluence", user_id="u1")
        assert "no longer supported" in result
        assert "API" in result


# ---------------------------------------------------------------------------
# LLM retry logic
# ---------------------------------------------------------------------------


class TestLLMRetry:
    @patch("metronix.llm.chat_completion")
    @patch("metronix.llm.time.sleep")
    def test_succeeds_on_second_attempt(
        self,
        mock_sleep: MagicMock,
        mock_cc: MagicMock,
    ) -> None:
        mock_cc.side_effect = [LLMConnectionError("timeout"), "success"]
        result = chat_completion_with_retry(
            messages=[{"role": "user", "content": "hi"}],
            max_retries=3,
            call_site="test",
        )
        assert result == "success"
        assert mock_cc.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch("metronix.llm.chat_completion")
    @patch("metronix.llm.time.sleep")
    def test_gives_up_after_max_retries(
        self,
        mock_sleep: MagicMock,
        mock_cc: MagicMock,
    ) -> None:
        mock_cc.side_effect = LLMConnectionError("network down")
        with pytest.raises(LLMConnectionError, match="network down"):
            chat_completion_with_retry(
                messages=[{"role": "user", "content": "hi"}],
                max_retries=3,
                call_site="test",
            )
        assert mock_cc.call_count == 3
        assert mock_sleep.call_count == 2  # sleeps between attempts, not after last

    @patch("metronix.llm.chat_completion")
    def test_does_not_retry_auth_errors(self, mock_cc: MagicMock) -> None:
        mock_cc.side_effect = LLMAuthenticationError("bad key")
        with pytest.raises(LLMAuthenticationError, match="bad key"):
            chat_completion_with_retry(
                messages=[{"role": "user", "content": "hi"}],
                max_retries=3,
                call_site="test",
            )
        assert mock_cc.call_count == 1

    @patch("metronix.llm.chat_completion")
    def test_succeeds_on_first_try(self, mock_cc: MagicMock) -> None:
        mock_cc.return_value = "instant"
        result = chat_completion_with_retry(
            messages=[{"role": "user", "content": "hi"}],
            max_retries=3,
            call_site="test",
        )
        assert result == "instant"
        assert mock_cc.call_count == 1


# ---------------------------------------------------------------------------
# Search pipeline degradation
# ---------------------------------------------------------------------------


class TestSearchDegradation:
    @patch("metronix.retrieval.search.chat_completion_with_retry", return_value="answer text")
    @patch(
        "metronix.retrieval.search.get_graph_entities",
        side_effect=ConnectionError("memgraph down"),
    )
    @patch("metronix.retrieval.search.recall_graph_async", return_value=[])
    @patch("metronix.retrieval.search.recall_metadata_async", return_value=[])
    @patch("metronix.retrieval.search.recall_exact_async", return_value=[])
    @patch("metronix.retrieval.search.recall_dense_async")
    @patch("metronix.retrieval.search.expand_query", side_effect=lambda q: q)
    @patch("metronix.retrieval.search.should_use_team_workflow_schema", return_value=False)
    async def test_graph_failure_continues_with_empty_data(
        self,
        _mock_schema: MagicMock,
        _mock_expand: MagicMock,
        mock_dense: MagicMock,
        _mock_exact: MagicMock,
        _mock_metadata: MagicMock,
        _mock_graph_channel: MagicMock,
        _mock_graph: MagicMock,
        mock_llm: MagicMock,
    ) -> None:
        mock_dense.return_value = [
            {
                "chunk_id": "c1",
                "doc_label": "DOC-1",
                "score": 0.9,
                "channel": "dense",
                "memory": {"memory": "doc1 content", "type": "confluence", "title": "Doc 1"},
            },
        ]
        from metronix.retrieval.search import hybrid_search_and_answer

        result = await hybrid_search_and_answer("test query")
        assert "answer text" in result
        mock_llm.assert_called_once()

    @patch(
        "metronix.retrieval.search.chat_completion_with_retry",
        side_effect=LLMError("all providers down"),
    )
    @patch("metronix.retrieval.search.get_entities_by_doc_labels", return_value=[])
    @patch("metronix.retrieval.search.recall_graph_async", return_value=[])
    @patch("metronix.retrieval.search.recall_metadata_async", return_value=[])
    @patch("metronix.retrieval.search.recall_exact_async", return_value=[])
    @patch("metronix.retrieval.search.recall_dense_async")
    @patch("metronix.retrieval.search.expand_query", side_effect=lambda q: q)
    @patch("metronix.retrieval.search.should_use_team_workflow_schema", return_value=False)
    async def test_llm_failure_returns_document_count(
        self,
        _mock_schema: MagicMock,
        _mock_expand: MagicMock,
        mock_dense: MagicMock,
        _mock_exact: MagicMock,
        _mock_metadata: MagicMock,
        _mock_graph: MagicMock,
        _mock_graph_ents: MagicMock,
        _mock_llm: MagicMock,
    ) -> None:
        from metronix.retrieval.channels import ScoredResult

        mock_dense.return_value = [
            ScoredResult(
                chunk_id="1",
                doc_label="L1",
                score=0.9,
                channel="dense",
                memory={"memory": "doc1", "type": "jira", "title": "T1", "doc_label": "L1"},
            ),
            ScoredResult(
                chunk_id="2",
                doc_label="L2",
                score=0.8,
                channel="dense",
                memory={"memory": "doc2", "type": "jira", "title": "T2", "doc_label": "L2"},
            ),
            ScoredResult(
                chunk_id="3",
                doc_label="L3",
                score=0.7,
                channel="dense",
                memory={"memory": "doc3", "type": "confluence", "title": "T3", "doc_label": "L3"},
            ),
        ]
        from metronix.retrieval.search import hybrid_search_and_answer

        result = await hybrid_search_and_answer("test query")
        assert "Found 3 relevant documents" in result
        assert "couldn't generate an answer" in result
