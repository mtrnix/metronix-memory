"""Unit tests for connection config-update recovery (#466).

Exercises PostgresStore.update_connection and inspects the SQL it emits.
No live Postgres required.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cryptography.fernet import Fernet

from metronix.storage.encryption import encrypt_value
from metronix.storage.postgres import PostgresStore

_FERNET_KEY = Fernet.generate_key().decode()

_JIRA_CONFIG = {
    "url": "https://acme.atlassian.net/",
    "username": "bot@acme.com",
    "api_token": "old-token",
    "project_key": "PROJ",
}

_CURSOR = datetime(2026, 9, 6, 9, 14, 22, tzinfo=UTC)


class _Row:
    def __init__(self, mapping: dict) -> None:
        self._mapping = mapping


class _SelectResult:
    def __init__(self, row: _Row | None) -> None:
        self._row = row

    def first(self) -> _Row | None:
        return self._row


class _FakeConn:
    def __init__(self, row: _Row | None) -> None:
        self._row = row
        self.executed: list[tuple[str, dict | None]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params))
        if "SELECT" in sql:
            return _SelectResult(self._row)
        return SimpleNamespace()


class _Begin:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *args) -> bool:
        return False


def _store(row: _Row | None) -> tuple[PostgresStore, _FakeConn]:
    conn = _FakeConn(row)
    store = PostgresStore.__new__(PostgresStore)
    store._engine = SimpleNamespace(begin=lambda: _Begin(conn))
    store.get_connection = AsyncMock(
        return_value={
            "id": "conn_001",
            "status": "active",
            "error_message": None,
            "last_synced_at": None,
        }
    )
    return store, conn


def _error_row(**overrides) -> _Row:
    mapping = {
        "id": "conn_001",
        "workspace_id": "ws_test",
        "connector_type": "jira",
        "name": "Jira",
        "config_encrypted": encrypt_value(json.dumps(_JIRA_CONFIG), _FERNET_KEY),
        "status": "error",
        "enabled": True,
        "error_message": "401 Unauthorized",
        "last_synced_at": _CURSOR,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": None,
    }
    mapping.update(overrides)
    return _Row(mapping)


def _updates(conn: _FakeConn) -> list[tuple[str, dict]]:
    out = []
    for sql, params in conn.executed:
        if "UPDATE connections" in sql:
            assert params is not None
            out.append((sql, params))
    return out


async def test_config_update_clears_error_status() -> None:
    """#466: rotating credentials must un-break a status=error row."""
    store, conn = _store(_error_row())

    await store.update_connection(
        "conn_001",
        {"config": {**_JIRA_CONFIG, "api_token": "fresh-token"}},
        _FERNET_KEY,
    )

    calls = _updates(conn)
    assert len(calls) == 1
    sql, params = calls[0]
    assert "config_encrypted = :config_encrypted" in sql
    assert "status = 'active'" in sql
    assert "error_message = NULL" in sql
    assert "status" not in params
    assert "error_message" not in params


async def test_config_update_nulls_last_synced_at() -> None:
    """#466: config change resets the incremental cursor so the next sync
    re-fetches documents the old credentials could not see."""
    store, conn = _store(_error_row())

    await store.update_connection(
        "conn_001",
        {"config": {**_JIRA_CONFIG, "api_token": "fresh-token"}},
        _FERNET_KEY,
    )

    calls = _updates(conn)
    assert len(calls) == 1
    sql, params = calls[0]
    assert "last_synced_at = NULL" in sql
    assert "last_synced_at" not in params


async def test_name_only_update_does_not_touch_status_or_cursor() -> None:
    """#466: a rename must not clear an error or wipe the incremental cursor."""
    store, conn = _store(_error_row())

    await store.update_connection("conn_001", {"name": "Jira renamed"}, _FERNET_KEY)

    calls = _updates(conn)
    assert len(calls) == 1
    sql, params = calls[0]
    assert "name = :name" in sql
    assert params["name"] == "Jira renamed"
    assert "status" not in params
    assert "error_message" not in params
    assert "last_synced_at" not in params
    assert "config_encrypted" not in params
    assert "status =" not in sql
    assert "error_message =" not in sql
    assert "last_synced_at =" not in sql


async def test_enabled_only_update_does_not_touch_status_or_cursor() -> None:
    """#466: toggling enabled is not a credential change."""
    store, conn = _store(_error_row())

    await store.update_connection("conn_001", {"enabled": False}, _FERNET_KEY)

    calls = _updates(conn)
    assert len(calls) == 1
    sql, params = calls[0]
    assert "enabled = :enabled" in sql
    assert params["enabled"] is False
    assert "status" not in params
    assert "error_message" not in params
    assert "last_synced_at" not in params
    assert "config_encrypted" not in params
