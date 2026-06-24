from metronix.core.config import Settings


def test_export_settings_defaults():
    s = Settings()
    assert s.public_base_url == ""
    assert s.export_dir == "/app/data/exports"
    assert s.export_token_ttl_seconds == 3600
    assert s.export_disk_cap_bytes == 5_000_000_000
    assert s.export_job_watchdog_seconds == 3600


def test_export_settings_env_override(monkeypatch):
    monkeypatch.setenv("METRONIX_PUBLIC_BASE_URL", "http://host:8001")
    monkeypatch.setenv("METRONIX_EXPORT_TOKEN_TTL_SECONDS", "120")
    s = Settings()
    assert s.public_base_url == "http://host:8001"
    assert s.export_token_ttl_seconds == 120
