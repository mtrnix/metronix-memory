"""Tests for dashboard sync-history query — filter + field coverage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from metronix.storage.dashboard_queries import get_sync_history_data
from metronix.storage.pg_connection import get_session
from metronix.storage.pg_models import ConnectionRow, SyncLogRow


@pytest.fixture
def ws():
    """Seed a workspace for tests using raw SQL to match the live DB schema."""
    import uuid

    from sqlalchemy import text

    ws_id = f"ws_test_{uuid.uuid4().hex[:12]}"
    with get_session() as s:
        s.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": ws_id, "name": "test", "slug": ws_id},
        )
    yield ws_id


@pytest.fixture
def conn(ws):
    """Seed a connection for tests."""
    import uuid

    cid = f"conn_test_{uuid.uuid4().hex[:12]}"
    with get_session() as s:
        s.add(
            ConnectionRow(
                id=cid,
                workspace_id=ws,
                connector_type="jira",
                name="Jira Test",
                config_encrypted=b"x",
                status="active",
                enabled=True,
            )
        )
    yield cid


def _make_sync_id(prefix: str = "sync") -> str:
    """Generate a unique sync log ID for tests."""
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _add_log(ws, conn, sync_id, status, fetched=10, new=3, chunks=3):
    with get_session() as s:
        s.add(
            SyncLogRow(
                id=sync_id,
                workspace_id=ws,
                connection_id=conn,
                connector_type="jira",
                status=status,
                documents_fetched=fetched,
                documents_new=new,
                documents_updated=0,
                documents_skipped=fetched - new,
                errors=[],
                duration_ms=1234.0,
                source_title="Jira Sync",
                qdrant_chunks=chunks,
                created_at=datetime.now(UTC),
            )
        )


def test_get_sync_history_returns_full_fields(ws, conn):
    sync_id = _make_sync_id("abc")
    _add_log(ws, conn, sync_id, "success")

    items = get_sync_history_data(ws, limit=10)

    assert len(items) >= 1
    item = next(i for i in items if i["id"] == sync_id)
    assert item["connection_id"] == conn
    assert item["connector_type"] == "jira"
    assert item["documents_fetched"] == 10
    assert item["documents_new"] == 3
    assert item["documents_updated"] == 0
    assert item["documents_skipped"] == 7
    assert item["qdrant_chunks"] == 3
    assert item["errors"] == []
    assert item["status"] == "success"


def test_get_sync_history_filters_by_connection_id(ws, conn):
    # Log for our connection
    sync_mine = _make_sync_id("mine")
    _add_log(ws, conn, sync_mine, "success")
    # Log for a different connection in the same workspace
    other_conn = f"conn_other_{_make_sync_id()}"
    with get_session() as s:
        s.add(
            ConnectionRow(
                id=other_conn,
                workspace_id=ws,
                connector_type="confluence",
                name="Other",
                config_encrypted=b"x",
                status="active",
                enabled=True,
            )
        )
    sync_other = _make_sync_id("other")
    _add_log(ws, other_conn, sync_other, "success")

    items = get_sync_history_data(ws, limit=10, connection_id=conn)

    ids = [i["id"] for i in items]
    assert sync_mine in ids
    assert sync_other not in ids


def test_get_sync_history_accepts_running_status(ws, conn):
    sync_id = _make_sync_id("running")
    _add_log(ws, conn, sync_id, "running", fetched=0, new=0, chunks=0)

    items = get_sync_history_data(ws, limit=10, connection_id=conn)

    item = next(i for i in items if i["id"] == sync_id)
    assert item["status"] == "running"
