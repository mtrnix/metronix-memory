"""Tests for Cypher-level temporal filtering in graph_ops.

Verifies that temporal WHERE clauses are pushed into Cypher queries
instead of being applied as Python post-filters.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_driver():
    """Create a mock Memgraph driver + session."""
    mock_session = MagicMock()
    mock_session.run.return_value = []
    mock_drv = MagicMock()
    mock_drv.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_drv.session.return_value.__exit__ = MagicMock(return_value=False)
    return mock_drv, mock_session


# --- 1. get_relationships_at_date includes temporal WHERE ---


class TestRelationshipsAtDateCypher:
    @patch("metatron.storage.graph_ops.get_graph_driver")
    def test_relationships_at_date_cypher_has_temporal_where(
        self,
        mock_get_driver: MagicMock,
    ) -> None:
        drv, session = _mock_driver()
        mock_get_driver.return_value = drv

        from metatron.storage.graph_ops import get_relationships_at_date

        get_relationships_at_date(["Alice"], target_date="2025-06-15", workspace_id="ws1")

        # Collect all Cypher strings passed to session.run()
        queries = [call[0][0] for call in session.run.call_args_list]
        assert len(queries) >= 2  # forward + reverse

        for q in queries:
            assert "r.valid_from IS NULL OR r.valid_from <= $td" in q
            assert "r.valid_to IS NULL OR r.valid_to >= $td" in q
        # Check params contain the target date
        for call in session.run.call_args_list:
            params = call[0][1] if len(call[0]) > 1 else call[1]
            assert params.get("td") == "2025-06-15"

    @patch("metatron.storage.graph_ops.get_graph_driver")
    def test_null_dates_included(self, mock_get_driver: MagicMock) -> None:
        """NULL valid_from/valid_to treated as 'always valid' via IS NULL checks."""
        drv, session = _mock_driver()
        mock_get_driver.return_value = drv

        from metatron.storage.graph_ops import get_relationships_at_date

        get_relationships_at_date(["X"], target_date="2025-01-01", workspace_id="ws1")

        queries = [call[0][0] for call in session.run.call_args_list]
        for q in queries:
            # IS NULL OR ensures rows with NULL dates pass through
            assert "r.valid_from IS NULL" in q
            assert "r.valid_to IS NULL" in q


# --- 2. active_only adds valid_to IS NULL in Cypher ---


class TestActiveOnlyCypher:
    @patch("metatron.storage.graph_ops.get_graph_driver")
    def test_active_only_cypher_has_valid_to_null(
        self,
        mock_get_driver: MagicMock,
    ) -> None:
        drv, session = _mock_driver()
        mock_get_driver.return_value = drv

        from metatron.storage.graph_ops import get_graph_relationships

        get_graph_relationships(["Alice"], workspace_id="ws1", active_only=True)

        queries = [call[0][0] for call in session.run.call_args_list]
        for q in queries:
            assert "r.valid_to IS NULL" in q

    @patch("metatron.storage.graph_ops.get_graph_driver")
    def test_active_only_false_no_valid_to_clause(
        self,
        mock_get_driver: MagicMock,
    ) -> None:
        drv, session = _mock_driver()
        mock_get_driver.return_value = drv

        from metatron.storage.graph_ops import get_graph_relationships

        get_graph_relationships(["Alice"], workspace_id="ws1", active_only=False)

        queries = [call[0][0] for call in session.run.call_args_list]
        for q in queries:
            assert "r.valid_to IS NULL" not in q


# --- 3. valid_after param in Cypher ---


class TestValidAfterCypher:
    @patch("metatron.storage.graph_ops.get_graph_driver")
    def test_valid_after_param_in_cypher(
        self,
        mock_get_driver: MagicMock,
    ) -> None:
        drv, session = _mock_driver()
        mock_get_driver.return_value = drv

        from metatron.storage.graph_ops import get_graph_relationships

        get_graph_relationships(
            ["Alice"],
            workspace_id="ws1",
            valid_after="2025-01-01",
        )

        queries = [call[0][0] for call in session.run.call_args_list]
        for q in queries:
            assert "r.valid_from IS NULL OR r.valid_from >= $valid_after" in q


# --- 4. valid_before param in Cypher ---


class TestValidBeforeCypher:
    @patch("metatron.storage.graph_ops.get_graph_driver")
    def test_valid_before_param_in_cypher(
        self,
        mock_get_driver: MagicMock,
    ) -> None:
        drv, session = _mock_driver()
        mock_get_driver.return_value = drv

        from metatron.storage.graph_ops import get_graph_relationships

        get_graph_relationships(
            ["Alice"],
            workspace_id="ws1",
            valid_before="2025-12-31",
        )

        queries = [call[0][0] for call in session.run.call_args_list]
        for q in queries:
            assert "r.valid_from IS NULL OR r.valid_from <= $valid_before" in q


# --- 5. ensure_graph_indexes idempotent ---


class TestEnsureIndexes:
    @patch("metatron.storage.neo4j_graph.get_graph_driver")
    def test_ensure_indexes_idempotent(
        self,
        mock_get_driver: MagicMock,
    ) -> None:
        drv, session = _mock_driver()
        mock_get_driver.return_value = drv

        from metatron.storage.neo4j_graph import ensure_graph_indexes

        # First call
        ensure_graph_indexes()
        first_count = session.run.call_count

        # Second call — no error even if indexes exist
        session.run.side_effect = Exception("Index already exists")
        ensure_graph_indexes()

        # Both calls completed without raising
        assert session.run.call_count > first_count
