"""Config flag: METRONIX_ACTIVITY_LOG_ENABLED, default true."""

from metronix.core.config import Settings


def test_activity_log_flag_defaults_true() -> None:
    settings = Settings()
    assert settings.activity_log_enabled is True


def test_activity_log_flag_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("METRONIX_ACTIVITY_LOG_ENABLED", "false")
    settings = Settings()
    assert settings.activity_log_enabled is False
