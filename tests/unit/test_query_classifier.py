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
