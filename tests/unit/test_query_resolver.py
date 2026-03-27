"""Tests for LLM-based query reference resolver."""

from __future__ import annotations

from unittest.mock import patch

from metatron.retrieval.search import resolve_query


class TestResolveQuery:
    """Tests for resolve_query() — LLM query reference resolver."""

    @patch("metatron.retrieval.search.chat_completion")
    def test_resolves_relative_date_from_context(self, mock_llm) -> None:
        mock_llm.return_value = "what was discussed on March 11?"
        query = (
            "context: what happened on March 12?"
            " | question: what was discussed the day before that?"
        )
        result = resolve_query(query)
        assert "March 11" in result
        assert "the day before that" not in result
        mock_llm.assert_called_once()

    @patch("metatron.retrieval.search.chat_completion")
    def test_resolves_pronoun_reference(self, mock_llm) -> None:
        mock_llm.return_value = "tell me more about Project Aurora"
        result = resolve_query(
            "context: What is Project Aurora? | question: tell me more about it"
        )
        assert "Project Aurora" in result
        mock_llm.assert_called_once()

    @patch("metatron.retrieval.search.chat_completion")
    def test_passthrough_standalone_query(self, mock_llm) -> None:
        mock_llm.return_value = "What is Metatron?"
        result = resolve_query("What is Metatron?")
        assert result == "What is Metatron?"

    @patch("metatron.retrieval.search.chat_completion")
    def test_fallback_on_llm_error(self, mock_llm) -> None:
        mock_llm.side_effect = Exception("LLM timeout")
        result = resolve_query("context: March 12 | question: day before that?")
        assert result == "context: March 12 | question: day before that?"

    @patch("metatron.retrieval.search.chat_completion")
    def test_fallback_on_empty_response(self, mock_llm) -> None:
        mock_llm.return_value = ""
        query = "context: March 12 | question: day before?"
        result = resolve_query(query)
        assert result == query

    @patch("metatron.retrieval.search.chat_completion")
    def test_fallback_on_too_short_response(self, mock_llm) -> None:
        mock_llm.return_value = "ab"
        query = "context: March 12 | question: what happened?"
        result = resolve_query(query)
        assert result == query

    @patch("metatron.retrieval.search.chat_completion")
    def test_fallback_on_too_long_response(self, mock_llm) -> None:
        query = "short query"
        mock_llm.return_value = "x" * (len(query) * 3 + 1)
        result = resolve_query(query)
        assert result == query

    @patch("metatron.retrieval.search.chat_completion")
    def test_russian_query_resolved(self, mock_llm) -> None:
        mock_llm.return_value = "что обсуждали 11 марта?"
        result = resolve_query(
            "context: что было 12 марта? | question: что обсуждали за день до этого?"
        )
        assert "11 марта" in result
        mock_llm.assert_called_once()

    @patch("metatron.retrieval.search.chat_completion")
    def test_prompt_contains_current_date(self, mock_llm) -> None:
        mock_llm.return_value = "resolved query"
        resolve_query("test query")
        call_args = mock_llm.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        user_msg = messages[1]["content"]
        assert "Current date:" in user_msg

    @patch("metatron.retrieval.search.chat_completion")
    def test_chat_history_format_resolved(self, mock_llm) -> None:
        mock_llm.return_value = "что обсуждали 11 марта?"
        query = (
            "Previous question: что было на митинге 12 марта?\n"
            "Current question: а за день до этого?"
        )
        result = resolve_query(query)
        assert "11 марта" in result
        mock_llm.assert_called_once()

    @patch("metatron.retrieval.search.chat_completion")
    def test_strips_whitespace(self, mock_llm) -> None:
        mock_llm.return_value = "  resolved query  \n"
        result = resolve_query("test query")
        assert result == "resolved query"
