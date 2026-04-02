"""Tests for agent/router.py — intent classification, routing, commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from metatron.agent.router import AgentRouter, Intent
from metatron.agent.sessions import SessionManager


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Reset SessionManager singleton before each test."""
    SessionManager.reset_instance()
    yield
    SessionManager.reset_instance()


@pytest.fixture
def settings():
    """Create a mock Settings object."""
    s = MagicMock()
    s.default_workspace_id = "TEST_WS"
    s.llm_provider = "deepseek"
    s.llm_fallback_provider = "ollama"
    return s


@pytest.fixture
def router(settings):
    """Create an AgentRouter with mock settings."""
    sessions = SessionManager()
    return AgentRouter(settings=settings, sessions=sessions)


class TestIntentClassification:
    def test_command_slash(self, router: AgentRouter) -> None:
        assert router._classify("/help") == Intent.COMMAND
        assert router._classify("/search query") == Intent.COMMAND
        assert router._classify("/sync") == Intent.COMMAND
        assert router._classify("/status") == Intent.COMMAND
        assert router._classify("/clear") == Intent.COMMAND

    def test_greeting_en(self, router: AgentRouter) -> None:
        assert router._classify("hello") == Intent.GREETING
        assert router._classify("Hello") == Intent.GREETING
        assert router._classify("hi") == Intent.GREETING
        assert router._classify("hey") == Intent.GREETING
        assert router._classify("Hello!") == Intent.GREETING

    def test_greeting_ru(self, router: AgentRouter) -> None:
        assert router._classify("привет") == Intent.GREETING
        assert router._classify("здравствуйте") == Intent.GREETING

    def test_smalltalk(self, router: AgentRouter) -> None:
        assert router._classify("how are you") == Intent.SMALLTALK
        assert router._classify("How are you doing?") == Intent.SMALLTALK
        assert router._classify("who are you") == Intent.SMALLTALK
        assert router._classify("как дела") == Intent.SMALLTALK
        assert router._classify("thanks") == Intent.SMALLTALK
        assert router._classify("спасибо") == Intent.SMALLTALK

    def test_search_default(self, router: AgentRouter) -> None:
        assert router._classify("what is MTRNIX-78 about?") == Intent.SEARCH
        assert router._classify("show me analytics dashboard") == Intent.SEARCH
        assert router._classify("архитектура проекта") == Intent.SEARCH


class TestRouteHelp:
    def test_help_command(self, router: AgentRouter) -> None:
        result = router.route("/help", user_id="u1")
        assert "/search" in result
        assert "/sync" in result
        assert "/status" in result
        assert "/clear" in result
        assert "/help" in result

    def test_unknown_command(self, router: AgentRouter) -> None:
        result = router.route("/foobar", user_id="u1")
        assert "Unknown command" in result
        assert "/help" in result


class TestRouteClear:
    def test_clear_command(self, router: AgentRouter) -> None:
        router._sessions.add_turn("u1", "TEST_WS", "user", "old msg")
        result = router.route("/clear", user_id="u1")
        assert "cleared" in result.lower()
        assert router._sessions.get_history("u1", "TEST_WS") == []


class TestRouteGreeting:
    def test_greeting_response(self, router: AgentRouter) -> None:
        result = router.route("hello", user_id="u1")
        assert "Metatron" in result
        assert "knowledge assistant" in result

    def test_start_command_returns_greeting(self, router: AgentRouter) -> None:
        result = router.route("/start", user_id="u1")
        assert "Metatron" in result
        assert "knowledge assistant" in result


class TestRouteSmallTalk:
    @patch("metatron.agent.router.chat_completion")
    def test_smalltalk_calls_llm(self, mock_llm, router: AgentRouter) -> None:
        mock_llm.return_value = "I'm doing great!"
        result = router.route("how are you", user_id="u1")
        assert result == "I'm doing great!"
        mock_llm.assert_called_once()

    @patch("metatron.agent.router.chat_completion")
    def test_smalltalk_fallback_on_error(self, mock_llm, router: AgentRouter) -> None:
        mock_llm.side_effect = RuntimeError("LLM down")
        result = router.route("how are you", user_id="u1")
        assert "Metatron" in result


class TestRouteSearch:
    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_search_calls_hybrid(self, mock_search, router: AgentRouter) -> None:
        mock_search.return_value = "Found: MTRNIX-78 is about analytics."
        result = router.route("what is MTRNIX-78?", user_id="u1")
        assert "MTRNIX-78" in result
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs["workspace_id"] == "TEST_WS"

    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_search_records_history(self, mock_search, router: AgentRouter) -> None:
        mock_search.return_value = "answer"
        router.route("query1", user_id="u1")
        history = router._sessions.get_history("u1", "TEST_WS")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "query1"
        assert history[1]["role"] == "assistant"

    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_search_command_dispatches(self, mock_search, router: AgentRouter) -> None:
        mock_search.return_value = "search result"
        result = router.route("/search MTRNIX-78", user_id="u1")
        assert result == "search result"
        mock_search.assert_called_once()

    def test_search_command_no_arg(self, router: AgentRouter) -> None:
        result = router.route("/search", user_id="u1")
        assert "Usage" in result

    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_composite_query_used(self, mock_search, router: AgentRouter) -> None:
        mock_search.return_value = "answer"
        router.route("tell me about team alpha", user_id="u1")
        router.route("what are their deadlines?", user_id="u1")
        # Second call: query=composite (with history), intent_query=current question
        second_call = mock_search.call_args_list[1]
        assert "team alpha" in second_call.kwargs["query"]
        assert second_call.kwargs["intent_query"] == "what are their deadlines?"

    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_intent_query_is_current_message(self, mock_search, router: AgentRouter) -> None:
        """Bug fix: intent_query must be the current message (for language detection),
        not the composite with history. English question after Russian history
        must have English-only intent_query."""
        mock_search.return_value = "answer"
        # Send 3 Russian questions to build history
        router.route("Расскажи про архитектуру", user_id="u1")
        router.route("Какие задачи в Jira?", user_id="u1")
        router.route("Что делает команда?", user_id="u1")
        # Now English question
        router.route("What the team doing this week?", user_id="u1")
        fourth_call = mock_search.call_args_list[3]
        # intent_query = current English question only (no Russian history)
        assert fourth_call.kwargs["intent_query"] == "What the team doing this week?"
        # query = independent question (no history — follow-up detection skips it)
        assert "What the team doing this week?" in fourth_call.kwargs["query"]

    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_search_error_handled(self, mock_search, router: AgentRouter) -> None:
        mock_search.side_effect = RuntimeError("Qdrant down")
        result = router.route("query", user_id="u1")
        assert "error" in result.lower()


class TestEmptyInput:
    def test_empty_string(self, router: AgentRouter) -> None:
        result = router.route("", user_id="u1")
        assert "/help" in result

    def test_whitespace_only(self, router: AgentRouter) -> None:
        result = router.route("   ", user_id="u1")
        assert "/help" in result


class TestRouteSync:
    def test_sync_returns_api_message(self, router: AgentRouter) -> None:
        result = router.route("/sync", user_id="u1")
        assert "no longer supported" in result
        assert "API" in result

    def test_sync_with_arg_returns_api_message(self, router: AgentRouter) -> None:
        result = router.route("/sync foobar", user_id="u1")
        assert "no longer supported" in result


class TestRouteStatus:
    def test_status_shows_workspace(self, router: AgentRouter) -> None:
        result = router.route("/status", user_id="u1")
        assert "TEST_WS" in result
        assert "LLM provider" in result
