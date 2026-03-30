"""Tests for memgraph_retry decorator and get_memgraph_driver liveness check."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from neo4j.exceptions import ServiceUnavailable, SessionExpired

import metatron.storage.memgraph as memgraph_mod
from metatron.storage.memgraph import memgraph_retry


class TestMemgraphRetry:
    def test_succeeds_first_attempt(self) -> None:
        @memgraph_retry()
        def ok():
            return "done"

        assert ok() == "done"

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_service_unavailable(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ServiceUnavailable("gone")
            return "recovered"

        assert flaky() == "recovered"
        assert calls["n"] == 2
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_session_expired(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise SessionExpired("expired")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 2
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_broken_pipe(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise BrokenPipeError("pipe")
            return "ok"

        assert flaky() == "ok"
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_generic_connection_string(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("connection reset by peer")
            return "ok"

        assert flaky() == "ok"
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_raises_after_max_attempts(self, mock_close) -> None:
        @memgraph_retry(max_attempts=3)
        def always_fails():
            raise ServiceUnavailable("down")

        with pytest.raises(ServiceUnavailable):
            always_fails()
        assert mock_close.call_count == 2  # called on attempts 1 and 2, not 3

    def test_non_connection_error_raises_immediately(self) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def bad():
            calls["n"] += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            bad()
        assert calls["n"] == 1  # no retry

    def test_preserves_function_args(self) -> None:
        @memgraph_retry()
        def add(a: int, b: int, extra: str = "") -> str:
            return f"{a + b}{extra}"

        assert add(2, 3) == "5"
        assert add(1, 2, extra="!") == "3!"


class TestGetMemgraphDriverLiveness:
    def setup_method(self):
        # Reset singleton before each test
        memgraph_mod._driver = None

    def teardown_method(self):
        memgraph_mod._driver = None

    def test_stale_driver_is_recreated(self) -> None:
        """A cached driver that fails verify_connectivity is replaced with a fresh one."""
        stale_driver = MagicMock()
        stale_driver.verify_connectivity.side_effect = ServiceUnavailable("stale")

        fresh_driver = MagicMock()
        fresh_driver.verify_connectivity.return_value = None

        memgraph_mod._driver = stale_driver

        with patch("metatron.storage.memgraph.GraphDatabase") as mock_gdb, \
             patch("metatron.core.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                memgraph_uri="bolt://localhost:7687",
                memgraph_user="",
                memgraph_password="",
            )
            mock_gdb.driver.return_value = fresh_driver

            result = memgraph_mod.get_memgraph_driver()

        assert result is fresh_driver
        mock_gdb.driver.assert_called_once()

    def test_healthy_driver_is_reused(self) -> None:
        """A cached driver that passes verify_connectivity is returned as-is."""
        healthy_driver = MagicMock()
        healthy_driver.verify_connectivity.return_value = None

        memgraph_mod._driver = healthy_driver

        with patch("metatron.storage.memgraph.GraphDatabase") as mock_gdb:
            result = memgraph_mod.get_memgraph_driver()

        assert result is healthy_driver
        mock_gdb.driver.assert_not_called()

    def test_driver_without_verify_connectivity_is_reused(self) -> None:
        """Older drivers without verify_connectivity are returned without error."""
        old_driver = MagicMock(spec=[])  # no verify_connectivity attribute

        memgraph_mod._driver = old_driver

        with patch("metatron.storage.memgraph.GraphDatabase") as mock_gdb:
            result = memgraph_mod.get_memgraph_driver()

        assert result is old_driver
        mock_gdb.driver.assert_not_called()
