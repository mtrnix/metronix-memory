"""Tests for query classifier: config, rule gate, LLM fallback, integration."""

from __future__ import annotations


class TestQueryClassifierConfig:
    def test_query_classifier_enabled_default_true(self) -> None:
        from metatron.core.config import Settings

        s = Settings()
        assert s.query_classifier_enabled is True

    def test_query_classifier_disabled_via_env(self, monkeypatch) -> None:
        from metatron.core.config import Settings

        monkeypatch.setenv("QUERY_CLASSIFIER_ENABLED", "false")
        s = Settings()
        assert s.query_classifier_enabled is False


import pytest


class TestProfileWeights:
    def test_all_profiles_exist(self) -> None:
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        expected = {"execution", "documentation", "user_file", "relationship", "temporal", "mixed"}
        assert set(QUERY_PROFILE_WEIGHTS.keys()) == expected

    @pytest.mark.parametrize("profile", [
        "execution", "documentation", "user_file", "relationship", "temporal", "mixed",
    ])
    def test_signal_weights_sum_to_085(self, profile: str) -> None:
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        w = QUERY_PROFILE_WEIGHTS[profile]
        signal_sum = (
            w["dense_weight"] + w["sparse_weight"] + w["graph_weight"]
            + w["metadata_weight"] + w["recency_weight"] + w["balance_weight"]
        )
        assert abs(signal_sum - 0.85) < 1e-9, f"{profile}: signal sum = {signal_sum}"

    @pytest.mark.parametrize("profile", [
        "execution", "documentation", "user_file", "relationship", "temporal", "mixed",
    ])
    def test_all_weight_keys_present(self, profile: str) -> None:
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        expected_keys = {
            "dense_weight", "sparse_weight", "graph_weight",
            "metadata_weight", "recency_weight", "balance_weight", "blend_weight",
        }
        assert set(QUERY_PROFILE_WEIGHTS[profile].keys()) == expected_keys

    def test_mixed_matches_current_defaults(self) -> None:
        """mixed profile must match compute_signal_score() defaults exactly."""
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        mixed = QUERY_PROFILE_WEIGHTS["mixed"]
        assert mixed["dense_weight"] == 0.35
        assert mixed["sparse_weight"] == 0.0
        assert mixed["graph_weight"] == 0.15
        assert mixed["metadata_weight"] == 0.20
        assert mixed["recency_weight"] == 0.10
        assert mixed["balance_weight"] == 0.05
        assert mixed["blend_weight"] == 0.30

    def test_get_profile_weights_valid(self) -> None:
        from metatron.retrieval.query_classifier import get_profile_weights

        w = get_profile_weights("execution")
        assert w["dense_weight"] == 0.20
        assert w["metadata_weight"] == 0.35

    def test_get_profile_weights_unknown_falls_back_to_mixed(self) -> None:
        from metatron.retrieval.query_classifier import get_profile_weights

        w = get_profile_weights("nonexistent")
        assert w == get_profile_weights("mixed")


class TestRuleGate:
    """Rule gate classifies obvious cases without LLM."""

    # -- execution profile --
    def test_jira_key_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is the status of MTRNIX-104?") == "execution"

    def test_jira_key_case_insensitive(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("mtrnix-104") == "execution"

    def test_status_keyword_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What tasks are in progress?") == "execution"

    def test_russian_status_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Что в работе?") == "execution"

    def test_sprint_keyword_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is in the current sprint?") == "execution"

    def test_backlog_keyword_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Show me the backlog") == "execution"

    # -- temporal profile --
    def test_date_expression_triggers_temporal(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What was done last week?") == "temporal"

    def test_this_month_triggers_temporal(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Show changes this month") == "temporal"

    def test_recently_triggers_temporal(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What was updated recently?") == "temporal"

    def test_russian_temporal_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Что было на этой неделе?") == "temporal"

    # -- user_file profile --
    def test_uploaded_triggers_user_file(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What does the uploaded document say?") == "user_file"

    def test_pdf_triggers_user_file(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Summarize the PDF report") == "user_file"

    def test_10k_triggers_user_file(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What does the 10K say?") == "user_file"

    def test_russian_file_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Что в загруженном файле?") == "user_file"

    def test_russian_file_word_forms(self) -> None:
        """файл prefix should match all word forms: файлы, файла, файле."""
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Покажи файлы") == "user_file"
        assert _rule_gate("Содержание файла") == "user_file"

    # -- relationship profile --
    def test_relationship_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("How does RBAC relate to auth?") == "relationship"

    def test_depends_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What depends on the auth module?") == "relationship"

    def test_between_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is the link between RBAC and users?") == "relationship"

    def test_russian_relationship_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Как связаны RBAC и пользователи?") == "relationship"

    # -- no match / ambiguous --
    def test_no_match_returns_none(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is Metatron?") is None

    def test_multiple_profiles_returns_none(self) -> None:
        """Query matching 2+ profiles should fall through to LLM."""
        from metatron.retrieval.query_classifier import _rule_gate

        # "in progress" → execution, "last week" → temporal
        assert _rule_gate("What was in progress last week?") is None

    # -- word boundary safety --
    def test_file_word_boundary(self) -> None:
        """'profile' should NOT match \\bfile\\b."""
        from metatron.retrieval.query_classifier import _rule_gate

        result = _rule_gate("Update the user profile settings")
        assert result != "user_file"

    def test_between_word_boundary(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("difference between A and B") == "relationship"


from unittest.mock import patch


class TestLLMFallback:
    """LLM fallback for queries the rule gate can't classify."""

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_returns_llm_profile(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "documentation", "confidence": 0.9}'
        result = _llm_classify("What is Metatron?")
        assert result["profile"] == "documentation"
        assert result["confidence"] == 0.9

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_low_confidence_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "documentation", "confidence": 0.3}'
        result = _llm_classify("vague query")
        assert result["profile"] == "mixed"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_invalid_json_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = "not json at all"
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_unknown_profile_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "nonexistent", "confidence": 0.95}'
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_timeout_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.side_effect = TimeoutError("LLM timeout")
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_exception_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.side_effect = RuntimeError("connection failed")
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_llm_called_with_correct_params(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "execution", "confidence": 0.8}'
        _llm_classify("test query")

        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["timeout"] == 10
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test query"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_llm_prompt_mentions_all_profiles(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "mixed", "confidence": 0.5}'
        _llm_classify("test query")

        system_prompt = mock_llm.call_args.kwargs["messages"][0]["content"]
        for profile in ("execution", "documentation", "user_file", "relationship", "temporal", "mixed"):
            assert profile in system_prompt


class TestClassifyQuery:
    """classify_query() orchestrates rule gate → LLM fallback."""

    def test_rule_gate_match_skips_llm(self) -> None:
        from metatron.retrieval.query_classifier import classify_query

        with patch("metatron.retrieval.query_classifier._llm_classify") as mock_llm:
            result = classify_query("What is MTRNIX-104?")
            mock_llm.assert_not_called()
        assert result["profile"] == "execution"
        assert result["method"] == "rule"
        assert result["confidence"] == 1.0

    @patch("metatron.retrieval.query_classifier._llm_classify")
    def test_no_rule_match_calls_llm(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import classify_query

        mock_llm.return_value = {"profile": "documentation", "confidence": 0.85, "method": "llm"}
        result = classify_query("What is Metatron?")
        mock_llm.assert_called_once()
        assert result["profile"] == "documentation"

    @patch("metatron.retrieval.query_classifier._llm_classify")
    def test_ambiguous_query_calls_llm(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import classify_query

        mock_llm.return_value = {"profile": "temporal", "confidence": 0.7, "method": "llm"}
        # Matches both execution ("in progress") and temporal ("last week")
        result = classify_query("What was in progress last week?")
        mock_llm.assert_called_once()
        assert result["profile"] == "temporal"

    def test_uses_original_query_not_translated(self) -> None:
        """Classifier should run on original query (rq), not expanded."""
        from metatron.retrieval.query_classifier import classify_query

        # Russian query with Jira key — rule gate should catch it
        result = classify_query("Статус MTRNIX-104?")
        assert result["profile"] == "execution"
        assert result["method"] == "rule"

    def test_translated_query_checked_for_english_keywords(self) -> None:
        """For Russian queries, translated_query is checked for English keywords too."""
        from metatron.retrieval.query_classifier import classify_query

        with patch("metatron.retrieval.query_classifier._llm_classify") as mock_llm:
            mock_llm.return_value = {"profile": "user_file", "confidence": 0.8, "method": "llm"}
            # translated_query contains "uploaded file" → user_file via rule gate
            result = classify_query(
                "Что в документе?",
                translated_query="What is in the uploaded file?",
            )
            mock_llm.assert_not_called()
        assert result["profile"] == "user_file"

    def test_exception_in_classify_returns_mixed(self) -> None:
        from metatron.retrieval.query_classifier import classify_query

        with patch("metatron.retrieval.query_classifier._rule_gate", side_effect=RuntimeError("boom")):
            result = classify_query("any query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"
