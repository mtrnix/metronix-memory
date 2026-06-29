import pytest

from metronix.mcp.config import get_default_workspace_id
from metronix.mcp.tools import _source_deps


class _FakeSettings:
    postgres_dsn = "postgresql+asyncpg://x/y"
    fernet_key = "test-key"


def test_resolve_defaults_workspace_to_server_default(monkeypatch):
    monkeypatch.setattr(_source_deps, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(_source_deps, "PostgresStore", lambda dsn: ("store", dsn))
    _source_deps._reset_cache_for_tests()

    ws_id, store, key = _source_deps.resolve(None)
    # An omitted workspace resolves to the server default, not a literal "default".
    assert ws_id == get_default_workspace_id()
    assert key == "test-key"


def test_resolve_uses_given_workspace(monkeypatch):
    monkeypatch.setattr(_source_deps, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(_source_deps, "PostgresStore", lambda dsn: ("store", dsn))
    _source_deps._reset_cache_for_tests()

    ws_id, _store, _key = _source_deps.resolve("teamA")
    assert ws_id == "teamA"


def test_resolve_raises_without_fernet_key(monkeypatch):
    class _NoKey(_FakeSettings):
        fernet_key = ""

    monkeypatch.setattr(_source_deps, "get_settings", lambda: _NoKey())
    monkeypatch.setattr(_source_deps, "PostgresStore", lambda dsn: ("store", dsn))
    _source_deps._reset_cache_for_tests()

    with pytest.raises(ValueError, match="FERNET_KEY"):
        _source_deps.resolve(None)
