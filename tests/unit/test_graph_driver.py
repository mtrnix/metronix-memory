"""Tests for graph_retry decorator and get_graph_driver liveness check."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable, SessionExpired

import metatron.storage.neo4j_graph as neo4j_graph_mod
from metatron.storage.neo4j_graph import graph_retry


class TestGraphRetry:
    def test_succeeds_first_attempt(self) -> None:
        @graph_retry()
        def ok():
            return "done"

        assert ok() == "done"

    @patch("metatron.storage.neo4j_graph.close_graph_driver")
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

    @patch("metatron.storage.neo4j_graph.close_graph_driver")
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

    @patch("metatron.storage.neo4j_graph.close_graph_driver")
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

    @patch("metatron.storage.neo4j_graph.close_graph_driver")
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

    @patch("metatron.storage.neo4j_graph.close_graph_driver")
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
            patch("metatron.storage.neo4j_graph.GraphDatabase") as mock_gdb,
            patch("metatron.core.config.get_settings") as mock_settings,
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

        with patch("metatron.storage.neo4j_graph.GraphDatabase") as mock_gdb:
            result = neo4j_graph_mod.get_graph_driver()

        assert result is healthy_driver
        mock_gdb.driver.assert_not_called()

    def test_driver_without_verify_connectivity_is_reused(self) -> None:
        """Older drivers without verify_connectivity are returned without error."""
        old_driver = MagicMock(spec=[])

        neo4j_graph_mod._driver = old_driver

        with patch("metatron.storage.neo4j_graph.GraphDatabase") as mock_gdb:
            result = neo4j_graph_mod.get_graph_driver()

        assert result is old_driver
        mock_gdb.driver.assert_not_called()
