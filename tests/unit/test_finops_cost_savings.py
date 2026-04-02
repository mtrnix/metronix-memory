"""Tests for FinOps cost savings — calculation logic, upsert, and aggregation."""

from __future__ import annotations

from collections import namedtuple
from datetime import date, timedelta
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
        upsert_document_fetch_stats_sync(
            "ws_test",
            {
                "doc:1": {"title": "T", "word_count": 10, "fetch_count": 1},
            },
        )


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


# Lightweight named tuple to mimic SQLAlchemy row results
_AggRow = namedtuple("_AggRow", ["doc_label", "title", "fetch_count", "total_context_words"])


class TestFetchCostSavingsAggregation:
    """Test _fetch_cost_savings aggregation and response building."""

    @patch("metatron.storage.pg_connection.get_session")
    def test_aggregates_all_docs_for_summary(self, mock_get_session):
        """Summary totals come from ALL docs, not just top N."""
        from metatron.api.routes.finops import _fetch_cost_savings

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        rows = [
            _AggRow("doc:A", "Doc A", 50, 10000),
            _AggRow("doc:B", "Doc B", 30, 5000),
            _AggRow("doc:C", "Doc C", 20, 3000),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        result = _fetch_cost_savings("ws1", date.today() - timedelta(days=30), limit=2)

        # Summary should count ALL 3 docs
        assert result["summary"]["total_documents"] == 3
        assert result["summary"]["total_fetches"] == 100  # 50 + 30 + 20

        # top_documents limited to 2
        assert len(result["top_documents"]) == 2
        assert result["top_documents"][0]["doc_label"] == "doc:A"
        assert result["top_documents"][1]["doc_label"] == "doc:B"

    @patch("metatron.storage.pg_connection.get_session")
    def test_empty_result_returns_zeroes(self, mock_get_session):
        """No data should return zero totals and empty top_documents."""
        from metatron.api.routes.finops import _fetch_cost_savings

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = _fetch_cost_savings("ws1", date.today() - timedelta(days=7), limit=20)

        assert result["summary"]["total_documents"] == 0
        assert result["summary"]["total_fetches"] == 0
        assert result["summary"]["metatron_cost"] == 0.0
        assert result["top_documents"] == []
        # All providers should have zero savings
        for provider in result["summary"]["providers"].values():
            assert provider["commercial_cost"] == 0.0
            assert provider["savings"] == 0.0

    @patch("metatron.storage.pg_connection.get_session")
    def test_response_schema_structure(self, mock_get_session):
        """Response structure matches CostSavingsResponse schema."""
        from metatron.api.routes.finops import _fetch_cost_savings

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        rows = [_AggRow("confluence:PAGE-1", "Architecture", 10, 2000)]
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_session.execute.return_value = mock_result

        result = _fetch_cost_savings("ws1", date.today() - timedelta(days=30), limit=20)

        # Summary structure
        summary = result["summary"]
        assert "total_documents" in summary
        assert "total_fetches" in summary
        assert "metatron_cost" in summary
        assert "providers" in summary
        expected_providers = {"openai_gpt4o", "anthropic_sonnet", "google_gemini"}
        assert set(summary["providers"].keys()) == expected_providers
        for prov in summary["providers"].values():
            assert "label" in prov
            assert "commercial_cost" in prov
            assert "savings" in prov
            assert "savings_pct" in prov

        # top_documents structure
        doc = result["top_documents"][0]
        assert "doc_label" in doc
        assert "title" in doc
        assert "fetch_count" in doc
        assert "total_context_words" in doc
        assert "costs" in doc
        assert "metatron_cost" in doc
        assert "max_savings" in doc

    @patch("metatron.storage.pg_connection.get_session")
    def test_db_error_returns_empty(self, mock_get_session):
        """DB failure should return empty results, not raise."""
        from metatron.api.routes.finops import _fetch_cost_savings

        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("connection refused")
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = _fetch_cost_savings("ws1", date.today() - timedelta(days=30), limit=20)

        assert result["summary"]["total_documents"] == 0
        assert result["top_documents"] == []
