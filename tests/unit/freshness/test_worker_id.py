"""Unit tests for ``build_worker_id`` (MTRNIX-316).

Covers shape, uniqueness, and the ``METRONIX_FRESHNESS_TEST_WORKER_ID``
override knob used by the SIGKILL integration test.
"""

from __future__ import annotations

import re

import pytest

from metronix.freshness.worker_id import build_worker_id


class TestShape:
    def test_matches_hostname_pid_uuid_pattern(self) -> None:
        wid = build_worker_id()
        # hostname may contain letters, digits, dashes, dots; never colons.
        assert re.match(r"^[^:]+:\d+:[0-9a-f]{8}$", wid), wid


class TestUniqueness:
    def test_two_calls_differ(self) -> None:
        a = build_worker_id()
        b = build_worker_id()
        assert a != b


class TestTestOverride:
    def test_env_override_returns_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_FRESHNESS_TEST_WORKER_ID", "pinned-test-worker")
        assert build_worker_id() == "pinned-test-worker"

    def test_empty_override_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METRONIX_FRESHNESS_TEST_WORKER_ID", "")
        wid = build_worker_id()
        assert re.match(r"^[^:]+:\d+:[0-9a-f]{8}$", wid), wid
