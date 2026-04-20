"""Tests for _run_connection_sync — initial row + finalize pattern."""

from __future__ import annotations

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
