"""Tests for LLM-based query expansion."""

from __future__ import annotations

from unittest.mock import patch

from metatron.retrieval.query_expansion import _build_expansion_prompt, expand_query


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
        expand_query("What is this?")
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

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_too_aggressive_expansion_rejected(self, mock_llm) -> None:
        """Expansion >4x original length is discarded entirely."""
        query = "What is Metatron?"
        mock_llm.return_value = "word " * 100  # way over 4x
        result = expand_query(query)
        assert result == query

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_over_3x_truncated(self, mock_llm) -> None:
        """Expansion between 3x and 4x is truncated to 3x budget."""
        query = "What is the team doing?"  # 24 chars
        # Return ~3.5x (84 chars) — should be truncated to ~72 chars (3x)
        mock_llm.return_value = (
            "team doing current tasks In Progress active sprint assigned текущие задачи в работе"
        )
        result = expand_query(query)
        assert len(result) <= len(query) * 3
        assert result.startswith("team")

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_under_3x_not_truncated(self, mock_llm) -> None:
        """Expansion within 3x is returned as-is."""
        query = "What is the team doing?"  # 24 chars
        expanded = "team doing In Progress active sprint"  # 36 chars = 1.5x
        mock_llm.return_value = expanded
        result = expand_query(query)
        assert result == expanded


class TestLanguageSpecificExpansion:
    def test_english_query_gets_english_prompt(self) -> None:
        prompt = _build_expansion_prompt("What is the team doing?")
        assert "Expand ONLY in English" in prompt
        assert "What is the team doing?" in prompt
        assert "Что делает команда?" not in prompt

    def test_russian_query_gets_russian_prompt(self) -> None:
        prompt = _build_expansion_prompt("Что делает команда?")
        assert "Expand ONLY in Russian" in prompt
        assert "Что делает команда?" in prompt
        assert "What is the team doing?" not in prompt

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_english_expansion_uses_english_prompt(self, mock_llm) -> None:
        mock_llm.return_value = "team doing current tasks In Progress active"
        expand_query("What is the team doing?")
        messages = mock_llm.call_args.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "ONLY in English" in system_msg

    @patch("metatron.retrieval.query_expansion.chat_completion")
    def test_russian_expansion_uses_russian_prompt(self, mock_llm) -> None:
        mock_llm.return_value = "команда делает текущие задачи В работе активные"
        expand_query("Что делает команда?")
        messages = mock_llm.call_args.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "ONLY in Russian" in system_msg
