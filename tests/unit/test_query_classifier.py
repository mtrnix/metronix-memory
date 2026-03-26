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
