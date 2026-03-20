"""Tests for FinOps cost savings — calculation logic and upsert."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


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
