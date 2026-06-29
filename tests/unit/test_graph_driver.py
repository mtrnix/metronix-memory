"""Tests for graph_retry decorator and get_graph_driver liveness check."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable, SessionExpired

import metronix.storage.neo4j_graph as neo4j_graph_mod
from metronix.storage.neo4j_graph import ensure_graph_indexes, graph_retry


class TestGraphRetry:
    def test_succeeds_first_attempt(self) -> None:
        @graph_retry()
        def ok():
            return "done"

        assert ok() == "done"

    @patch("metronix.storage.neo4j_graph.close_graph_driver")
    def test_retries_on_service_unavailable(self, mock_close) -> None:
        calls = {"n": 0}

        @graph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ServiceUnavailable("gone")
            return "recovered"

        assert flaky() == "recovered"
        assert calls["n"] == 2
        mock_close.assert_called_once()

    @patch("metronix.storage.neo4j_graph.close_graph_driver")
    def test_retries_on_session_expired(self, mock_close) -> None:
        calls = {"n": 0}

        @graph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise SessionExpired("expired")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 2
        mock_close.assert_called_once()

    @patch("metronix.storage.neo4j_graph.close_graph_driver")
    def test_retries_on_broken_pipe(self, mock_close) -> None:
        calls = {"n": 0}

        @graph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise BrokenPipeError("pipe")
            return "ok"

        assert flaky() == "ok"
        mock_close.assert_called_once()

    @patch("metronix.storage.neo4j_graph.close_graph_driver")
    def test_retries_on_generic_connection_string(self, mock_close) -> None:
        calls = {"n": 0}

        @graph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("connection reset by peer")
            return "ok"

        assert flaky() == "ok"
        mock_close.assert_called_once()

    @patch("metronix.storage.neo4j_graph.close_graph_driver")
    def test_raises_after_max_attempts(self, mock_close) -> None:
        @graph_retry(max_attempts=3)
        def always_fails():
            raise ServiceUnavailable("down")

        with pytest.raises(ServiceUnavailable):
            always_fails()
        assert mock_close.call_count == 2  # called on attempts 1 and 2, not 3

    def test_non_connection_error_raises_immediately(self) -> None:
        calls = {"n": 0}

        @graph_retry()
        def bad():
            calls["n"] += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            bad()
        assert calls["n"] == 1  # no retry

    def test_preserves_function_args(self) -> None:
        @graph_retry()
        def add(a: int, b: int, extra: str = "") -> str:
            return f"{a + b}{extra}"

        assert add(2, 3) == "5"
        assert add(1, 2, extra="!") == "3!"


class TestGetGraphDriverLiveness:
    def setup_method(self):
        neo4j_graph_mod._driver = None

    def teardown_method(self):
        neo4j_graph_mod._driver = None

    def test_stale_driver_is_recreated(self) -> None:
        """A cached driver that fails verify_connectivity is replaced with a fresh one."""
        stale_driver = MagicMock()
        stale_driver.verify_connectivity.side_effect = ServiceUnavailable("stale")

        fresh_driver = MagicMock()
        fresh_driver.verify_connectivity.return_value = None

        neo4j_graph_mod._driver = stale_driver

        with (
            patch("metronix.storage.neo4j_graph.GraphDatabase") as mock_gdb,
            patch("metronix.core.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value = MagicMock(
                neo4j_uri="bolt://localhost:7687",
                neo4j_user="",
                neo4j_password="",
            )
            mock_gdb.driver.return_value = fresh_driver

            result = neo4j_graph_mod.get_graph_driver()

        assert result is fresh_driver
        mock_gdb.driver.assert_called_once()

    def test_healthy_driver_is_reused(self) -> None:
        """A cached driver that passes verify_connectivity is returned as-is."""
        healthy_driver = MagicMock()
        healthy_driver.verify_connectivity.return_value = None

        neo4j_graph_mod._driver = healthy_driver

        with patch("metronix.storage.neo4j_graph.GraphDatabase") as mock_gdb:
            result = neo4j_graph_mod.get_graph_driver()

        assert result is healthy_driver
        mock_gdb.driver.assert_not_called()

    def test_driver_without_verify_connectivity_is_reused(self) -> None:
        """Older drivers without verify_connectivity are returned without error."""
        old_driver = MagicMock(spec=[])

        neo4j_graph_mod._driver = old_driver

        with patch("metronix.storage.neo4j_graph.GraphDatabase") as mock_gdb:
            result = neo4j_graph_mod.get_graph_driver()

        assert result is old_driver
        mock_gdb.driver.assert_not_called()


class TestEnsureGraphIndexes:
    def test_creates_all_indexes(self) -> None:
        """ensure_graph_indexes runs all 9 CREATE INDEX statements."""
        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("metronix.storage.neo4j_graph.get_graph_driver", return_value=mock_driver):
            ensure_graph_indexes()

        stmts = [call.args[0] for call in mock_session.run.call_args_list]
        assert len(stmts) == 9

        # Original indexes
        assert "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.name)" in stmts
        assert "CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.workspace_id)" in stmts
        assert "CREATE INDEX IF NOT EXISTS FOR (d:Document) ON (d.doc_label)" in stmts
        assert "CREATE INDEX IF NOT EXISTS FOR (d:Document) ON (d.workspace_id)" in stmts
        assert "CREATE INDEX IF NOT EXISTS FOR (j:JiraIssue) ON (j.issue_key)" in stmts
        assert "CREATE INDEX IF NOT EXISTS FOR (j:JiraIssue) ON (j.workspace_id)" in stmts

        # Agent Memory indexes
        assert "CREATE INDEX IF NOT EXISTS FOR (a:Agent) ON (a.workspace_id)" in stmts
        assert (
            "CREATE INDEX IF NOT EXISTS FOR (m:MemoryRecord) ON (m.workspace_id, m.scope)" in stmts
        )
        assert "CREATE INDEX IF NOT EXISTS FOR (m:MemoryRecord) ON (m.ttl_expires_at)" in stmts

    def test_continues_on_index_error(self) -> None:
        """A failing index statement does not prevent subsequent indexes."""
        mock_session = MagicMock()
        mock_session.run.side_effect = [
            None,  # Entity name
            Exception("already exists"),  # Entity workspace_id
            None,
            None,
            None,
            None,  # Document + JiraIssue
            None,
            None,
            None,  # Agent Memory
        ]
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("metronix.storage.neo4j_graph.get_graph_driver", return_value=mock_driver):
            ensure_graph_indexes()

        assert mock_session.run.call_count == 9
