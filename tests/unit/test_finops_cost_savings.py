"""Tests for FinOps cost savings — calculation logic and upsert."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestUpsertDocumentFetchStats:
    """Test upsert_document_fetch_stats_sync builds correct SQL."""

    @patch("metatron.storage.pg_connection.get_session")
    def test_upsert_inserts_rows(self, mock_get_session):
        """Verify upsert executes INSERT ON CONFLICT for each doc."""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        from metatron.storage.pg_connection import upsert_document_fetch_stats_sync

        doc_stats = {
            "confluence:PAGE-1": {"title": "Doc One", "word_count": 100, "fetch_count": 2},
            "jira:MTRNIX-42": {"title": "Doc Two", "word_count": 50, "fetch_count": 1},
        }
        upsert_document_fetch_stats_sync("ws_test", doc_stats)

        assert mock_session.execute.called
        mock_session.commit.assert_called_once()

    @patch("metatron.storage.pg_connection.get_session")
    def test_upsert_empty_stats_does_nothing(self, mock_get_session):
        """Empty doc_stats should not call execute."""
        from metatron.storage.pg_connection import upsert_document_fetch_stats_sync

        upsert_document_fetch_stats_sync("ws_test", {})
        mock_get_session.assert_not_called()

    @patch("metatron.storage.pg_connection.get_session")
    def test_upsert_db_error_does_not_raise(self, mock_get_session):
        """DB failure should log warning, not raise."""
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("DB down")
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        from metatron.storage.pg_connection import upsert_document_fetch_stats_sync

        # Should not raise
        upsert_document_fetch_stats_sync("ws_test", {
            "doc:1": {"title": "T", "word_count": 10, "fetch_count": 1},
        })


class TestCostCalculation:
    """Test commercial cost calculation logic."""

    def test_single_provider_cost(self):
        """GPT-4o: 1000 words, 5 fetches."""
        from metatron.api.routes.finops import _calculate_doc_costs

        costs = _calculate_doc_costs(total_context_words=1000, fetch_count=5)

        # Input: 1000 * 1.6 = 1600 tokens
        # GPT-4o input cost: 1600 * 2.50 / 1_000_000 = 0.004
        # GPT-4o output cost: 500 * 10.00 / 1_000_000 * 5 = 0.025
        # GPT-4o total: 0.029
        assert abs(costs["openai_gpt4o"] - 0.029) < 0.001

    def test_metatron_cost(self):
        """Metatron cost is INFRA_COST_PER_QUERY * fetch_count."""
        from metatron.api.routes.finops import _metatron_cost

        assert abs(_metatron_cost(10) - 0.005) < 0.0001

    def test_zero_fetches(self):
        """Zero fetches should return zero costs."""
        from metatron.api.routes.finops import _calculate_doc_costs

        costs = _calculate_doc_costs(total_context_words=0, fetch_count=0)
        assert all(v == 0.0 for v in costs.values())

    def test_all_providers_present(self):
        """All 3 providers should be in the result."""
        from metatron.api.routes.finops import _calculate_doc_costs

        costs = _calculate_doc_costs(total_context_words=100, fetch_count=1)
        assert "openai_gpt4o" in costs
        assert "anthropic_sonnet" in costs
        assert "google_gemini" in costs

    def test_anthropic_more_expensive_than_google(self):
        """Claude Sonnet should cost more than Gemini for same input."""
        from metatron.api.routes.finops import _calculate_doc_costs

        costs = _calculate_doc_costs(total_context_words=5000, fetch_count=10)
        assert costs["anthropic_sonnet"] > costs["google_gemini"]
