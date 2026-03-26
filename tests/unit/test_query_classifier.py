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
