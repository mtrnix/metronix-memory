"""Unit tests for freshness-reliability settings (MTRNIX-316).

Covers the six new knobs added in Task 2:

* ``METATRON_FRESHNESS_HEARTBEAT_TTL_SECONDS``
* ``METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS``
* ``METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED``
* ``METATRON_FRESHNESS_SCHEDULED_SCAN_INTERVAL_SECONDS``
* ``METATRON_FRESHNESS_SCAN_BATCH_LIMIT``
* ``METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP``

Defaults are chosen so enabling the flag-gated features is a no-op for
pre-MTRNIX-316 dev rigs.
"""

from __future__ import annotations

import pytest

from metatron.core.config import Settings


class TestDefaults:
    def test_heartbeat_ttl_default(self) -> None:
        s = Settings()
        assert s.freshness_heartbeat_ttl_seconds == 20

    def test_reclaim_interval_iterations_default(self) -> None:
        s = Settings()
        assert s.freshness_reclaim_interval_iterations == 30

    def test_scheduled_scan_enabled_default(self) -> None:
        s = Settings()
        assert s.freshness_scheduled_scan_enabled is True

    def test_scheduled_scan_interval_seconds_default(self) -> None:
        s = Settings()
        assert s.freshness_scheduled_scan_interval_seconds == 3600

    def test_scan_batch_limit_default(self) -> None:
        s = Settings()
        assert s.freshness_scan_batch_limit == 500

    def test_drain_legacy_default(self) -> None:
        s = Settings()
        assert s.freshness_drain_legacy_at_startup is False


class TestEnvOverrides:
    def test_heartbeat_ttl_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_HEARTBEAT_TTL_SECONDS", "45")
        s = Settings()
        assert s.freshness_heartbeat_ttl_seconds == 45

    def test_reclaim_interval_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS", "5")
        s = Settings()
        assert s.freshness_reclaim_interval_iterations == 5

    def test_scheduled_scan_enabled_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED", "false")
        s = Settings()
        assert s.freshness_scheduled_scan_enabled is False

    def test_scheduled_scan_interval_seconds_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_SCHEDULED_SCAN_INTERVAL_SECONDS", "60")
        s = Settings()
        assert s.freshness_scheduled_scan_interval_seconds == 60

    def test_scan_batch_limit_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_SCAN_BATCH_LIMIT", "100")
        s = Settings()
        assert s.freshness_scan_batch_limit == 100

    def test_drain_legacy_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP", "true")
        s = Settings()
        assert s.freshness_drain_legacy_at_startup is True


class TestBoolParsing:
    @pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
    def test_scheduled_scan_enabled_false_variants(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED", value)
        s = Settings()
        assert s.freshness_scheduled_scan_enabled is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
    def test_drain_legacy_true_variants(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP", value)
        s = Settings()
        assert s.freshness_drain_legacy_at_startup is True
