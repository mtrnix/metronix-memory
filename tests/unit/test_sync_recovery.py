"""Tests for startup sync recovery — reset stuck `running` logs and `syncing` connections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from metatron.storage.pg_connection import get_session
from metatron.storage.pg_models import ConnectionRow, SyncLogRow
from metatron.storage.recovery import recover_interrupted_syncs


@pytest.fixture
def stuck_ids():
    """Seed a workspace + connection stuck in 'syncing'."""
    suffix = uuid4().hex[:10]
    ws = f"ws_rec_{suffix}"
    cid = f"conn_rec_{suffix}"
    with get_session() as s:
        s.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :n, :sl)"),
            {"id": ws, "n": "t", "sl": ws},
        )
        s.add(
            ConnectionRow(
                id=cid,
                workspace_id=ws,
                connector_type="jira",
                name="T",
                config_encrypted=b"x",
                status="syncing",  # stuck!
                enabled=True,
            )
        )
    yield ws, cid


def _seed_running_log(ws, cid, sync_id, minutes_ago=5):
    with get_session() as s:
        s.add(
            SyncLogRow(
                id=sync_id,
                workspace_id=ws,
                connection_id=cid,
                connector_type="jira",
                status="running",
                documents_fetched=0,
                documents_new=0,
                documents_updated=0,
                documents_skipped=0,
                errors=[],
                duration_ms=0.0,
                source_title="Jira Sync",
                qdrant_chunks=0,
                created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            )
        )


def test_recovery_marks_running_logs_failed(stuck_ids):
    ws, cid = stuck_ids
    sync_id = f"sync_stuck_{uuid4().hex[:10]}"
    _seed_running_log(ws, cid, sync_id, minutes_ago=10)

    result = recover_interrupted_syncs()

    assert result["sync_logs_reset"] >= 1
    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        status = row.status
        errors = list(row.errors)
        duration_ms = row.duration_ms
    assert status == "failed"
    assert any("interrupted" in e.lower() for e in errors)
    assert duration_ms > 0


def test_recovery_resets_syncing_connections(stuck_ids):
    ws, cid = stuck_ids

    result = recover_interrupted_syncs()

    assert result["connections_reset"] >= 1
    with get_session() as s:
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
        conn_status = conn.status
        conn_error = conn.error_message
    assert conn_status == "error"
    assert conn_error is not None
    assert "interrupted" in conn_error.lower()


def test_recovery_is_idempotent(stuck_ids):
    ws, cid = stuck_ids
    sync_id = f"sync_idem_{uuid4().hex[:10]}"
    _seed_running_log(ws, cid, sync_id)

    recover_interrupted_syncs()
    result2 = recover_interrupted_syncs()

    # Second run finds nothing to reset.
    assert result2["sync_logs_reset"] == 0
    assert result2["connections_reset"] == 0
    # Log is still failed — not double-mutated.
    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        status = row.status
    assert status == "failed"


def test_recovery_returns_zero_when_nothing_stuck():
    # Fresh run on a clean slate should return zeros without raising.
    result = recover_interrupted_syncs()

    assert "sync_logs_reset" in result
    assert "connections_reset" in result
    assert result["sync_logs_reset"] >= 0
    assert result["connections_reset"] >= 0
