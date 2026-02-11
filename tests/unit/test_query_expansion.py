"""Tests for LLM-based query expansion."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from metatron.retrieval.query_expansion import expand_query


class TestExpandQuery:
    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_returns_expanded_string(self, mock_llm) -> None:
        mock_llm.return_value = "team current tasks In Progress active sprint assigned"
        result = expand_query("What is the team doing?")
        assert "In Progress" in result
        assert len(result) > len("What is the team doing?")
        mock_llm.assert_called_once()

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_fallback_on_error(self, mock_llm) -> None:
        mock_llm.side_effect = Exception("LLM timeout")
        result = expand_query("test query")
        assert result == "test query"

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_fallback_on_empty_response(self, mock_llm) -> None:
        mock_llm.return_value = ""
        result = expand_query("test query")
        assert result == "test query"

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_fallback_on_shorter_response(self, mock_llm) -> None:
        """If LLM returns something shorter than original, use original."""
        mock_llm.return_value = "short"
        result = expand_query("a longer original query")
        assert result == "a longer original query"

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_strips_quotes(self, mock_llm) -> None:
        mock_llm.return_value = '"team tasks In Progress sprint assigned"'
        result = expand_query("What is the team doing?")
        assert not result.startswith('"')
        assert not result.endswith('"')

    def test_disabled_by_config(self, monkeypatch) -> None:
        monkeypatch.setenv("QUERY_EXPANSION_ENABLED", "false")
        result = expand_query("test query")
        assert result == "test query"

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_prompt_contains_system_instructions(self, mock_llm) -> None:
        mock_llm.return_value = "expanded query with extra keywords added"
        expand_query("test")
        call_args = mock_llm.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        system_msg = messages[0]["content"]
        assert "BM25" in system_msg
        assert "In Progress" in system_msg

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_uses_low_temperature(self, mock_llm) -> None:
        mock_llm.return_value = "expanded query with keywords"
        expand_query("test")
        call_args = mock_llm.call_args
        assert call_args.kwargs.get("temperature") == 0.1

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_respects_timeout(self, mock_llm) -> None:
        mock_llm.return_value = "expanded query with keywords"
        expand_query("test", timeout=5)
        call_args = mock_llm.call_args
        assert call_args.kwargs.get("timeout") == 5
