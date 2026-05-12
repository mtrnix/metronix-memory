"""Tests for _run_connection_sync — initial row + finalize pattern."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text

from metatron.api.routes.connections import _run_connection_sync
from metatron.core.config import Settings
from metatron.core.models import Document
from metatron.storage.pg_connection import get_session
from metatron.storage.pg_models import ConnectionRow, SyncLogRow
from metatron.storage.postgres import PostgresStore


@pytest.fixture
async def store():
    yield PostgresStore(Settings().postgres_dsn)


@pytest.fixture
def seeded_ids():
    suffix = uuid4().hex[:10]
    ws = f"ws_rcs_{suffix}"
    cid = f"conn_rcs_{suffix}"
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
                status="syncing",
                enabled=True,
            )
        )
    yield ws, cid


async def test_run_connection_sync_finalizes_running_row_on_success(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_success_{uuid4().hex[:10]}"

    # Pre-insert the running row (simulates what trigger_sync did)
    await store.create_sync_log(sync_id, ws, cid, "jira")

    # Stub: connector returns 1 doc; ingest returns all-new
    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(
        return_value=[
            Document(
                source_type="jira",
                source_id="J-1",
                url="",
                workspace_id=ws,
                title="t",
                content="c",
                author="a",
                metadata={},
            )
        ]
    )

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    fake_ingest_result = MagicMock(
        documents_new=1,
        documents_updated=0,
        documents_skipped=0,
        errors=[],
    )

    with (
        patch("metatron.api.routes.connections._get_registry", return_value=fake_registry),
        patch(
            "metatron.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=fake_ingest_result),
        ),
        patch(
            "metatron.ingestion.pipeline.process_all_unsynced_graphs",
            AsyncMock(return_value={"ok": 1, "errors": 0}),
        ),
    ):
        await _run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            workspace_id=ws,
            store=store,
            event_bus=None,
        )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
        assert row.status == "success"
        assert row.documents_new == 1
        assert row.duration_ms > 0
        assert conn.status == "active"
        assert conn.last_synced_at is not None


async def test_run_connection_sync_marks_failed_on_exception(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_fail_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(side_effect=RuntimeError("Jira 500"))

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with patch("metatron.api.routes.connections._get_registry", return_value=fake_registry):
        await _run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x"},
            workspace_id=ws,
            store=store,
            event_bus=None,
        )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
        assert row.status == "failed"
        assert any("Jira 500" in e for e in row.errors)
        assert conn.status == "error"
        assert "Jira 500" in (conn.error_message or "")


# ---------------------------------------------------------------------------
# force_full flag (MTRNIX-332)
# ---------------------------------------------------------------------------


async def test_run_connection_sync_force_full_bypasses_sync_state(store, seeded_ids):
    """force_full=True must pass since=None to fetch and skip SyncState read."""
    ws, cid = seeded_ids
    sync_id = f"sync_force_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    # SyncState would normally return a stale cursor — verify we ignore it.
    stale_cursor = datetime(2099, 1, 1, tzinfo=UTC)
    mock_sync_state = MagicMock()
    mock_sync_state.get_last_sync = MagicMock(return_value=stale_cursor)
    mock_sync_state.set_last_sync = MagicMock()

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[])

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with (
        patch("metatron.api.routes.connections._get_registry", return_value=fake_registry),
        patch("metatron.connectors.sync_state.SyncState", return_value=mock_sync_state),
        patch(
            "metatron.ingestion.pipeline.ingest_documents",
            AsyncMock(
                return_value=MagicMock(
                    documents_new=0,
                    documents_updated=0,
                    documents_skipped=0,
                    errors=[],
                )
            ),
        ),
    ):
        await _run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            force_full=True,
        )

    # The whole point: fetch was called with since=None despite the stale cursor.
    fake_connector.fetch.assert_awaited_once()
    call_kwargs = fake_connector.fetch.await_args.kwargs
    assert call_kwargs.get("since") is None, (
        f"force_full=True must pass since=None, got {call_kwargs.get('since')!r}"
    )
    # SyncState.get_last_sync must NOT have been called — we bypass it entirely.
    mock_sync_state.get_last_sync.assert_not_called()


async def test_run_connection_sync_default_reads_sync_state(store, seeded_ids):
    """force_full=False (default) keeps the cursor read — regression guard."""
    ws, cid = seeded_ids
    sync_id = f"sync_default_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    cursor = datetime(2026, 5, 1, tzinfo=UTC)
    mock_sync_state = MagicMock()
    mock_sync_state.get_last_sync = MagicMock(return_value=cursor)
    mock_sync_state.set_last_sync = MagicMock()

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[])

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with (
        patch("metatron.api.routes.connections._get_registry", return_value=fake_registry),
        patch("metatron.connectors.sync_state.SyncState", return_value=mock_sync_state),
        patch(
            "metatron.ingestion.pipeline.ingest_documents",
            AsyncMock(
                return_value=MagicMock(
                    documents_new=0,
                    documents_updated=0,
                    documents_skipped=0,
                    errors=[],
                )
            ),
        ),
    ):
        await _run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            # force_full omitted — defaults to False
        )

    fake_connector.fetch.assert_awaited_once()
    assert fake_connector.fetch.await_args.kwargs.get("since") == cursor
    mock_sync_state.get_last_sync.assert_called_once_with(ws, "jira")


# ---------------------------------------------------------------------------
# Concurrent-sync guard (MTRNIX-332)
# ---------------------------------------------------------------------------


async def test_trigger_sync_returns_409_when_connection_is_syncing(seeded_ids):
    """A POST /sync/ against a connection with status='syncing' returns 409.

    Best-effort guard (racy — see route comment). Verifies the common case:
    operator hits the button twice in a row, second hit is rejected.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from metatron.api.routes.connections import router as connections_router

    ws, cid = seeded_ids

    # Mock the store so get_connection_decrypted returns a syncing connection.
    mock_store = MagicMock()
    mock_store.get_connection_decrypted = AsyncMock(
        return_value={
            "id": cid,
            "workspace_id": ws,
            "connector_type": "jira",
            "config": {"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            "status": "syncing",  # already running
            "enabled": True,
        }
    )
    mock_store.create_sync_log = AsyncMock()
    mock_store.update_connection_status = AsyncMock()

    app = FastAPI()
    app.state.settings = MagicMock(fernet_key="x" * 44, default_workspace_id=ws)
    app.state.postgres = mock_store
    app.include_router(connections_router, prefix="/api/v1")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(f"/api/v1/connections/{cid}/sync/?force_full=true")

    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"].lower()
    # Crucially: no sync log written, no status change, no background task.
    mock_store.create_sync_log.assert_not_awaited()
    mock_store.update_connection_status.assert_not_awaited()
