"""Tests for PostgresStore.create_sync_log / update_sync_log helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from metatron.core.config import Settings
from metatron.storage.pg_connection import get_engine, get_session
from metatron.storage.pg_models import SyncLogRow
from metatron.storage.postgres import PostgresStore


@pytest.fixture
async def store():
    s = Settings()
    yield PostgresStore(s.postgres_dsn)


@pytest.fixture
def seeded_ids():
    suffix = uuid4().hex[:10]
    ws_id = f"ws_sl_{suffix}"
    cid = f"conn_sl_{suffix}"
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": ws_id, "name": "t", "slug": ws_id},
        )
        conn.execute(
            text(
                "INSERT INTO connections"
                " (id, workspace_id, connector_type, name, config_encrypted, status, enabled)"
                " VALUES (:id, :ws, 'jira', 'T', :cfg, 'active', true)"
            ),
            {"id": cid, "ws": ws_id, "cfg": b"x"},
        )
        conn.commit()
    yield ws_id, cid


async def test_create_sync_log_inserts_running_row(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_create_{uuid4().hex[:10]}"

    await store.create_sync_log(
        sync_id=sync_id,
        workspace_id=ws,
        connection_id=cid,
        connector_type="jira",
    )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        assert row is not None
        assert row.status == "running"
        assert row.documents_fetched == 0
        assert row.qdrant_chunks == 0
        assert row.errors == []
        assert row.source_title == "Jira Sync"
        assert row.created_at is not None


async def test_update_sync_log_finalizes_row(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_update_{uuid4().hex[:10]}"
    await store.create_sync_log(
        sync_id=sync_id,
        workspace_id=ws,
        connection_id=cid,
        connector_type="jira",
    )

    await store.update_sync_log(
        sync_id=sync_id,
        status="success",
        documents_fetched=297,
        documents_new=22,
        documents_updated=5,
        documents_skipped=270,
        qdrant_chunks=27,
        errors=[],
        duration_ms=6700.5,
    )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        assert row.status == "success"
        assert row.documents_fetched == 297
        assert row.documents_new == 22
        assert row.qdrant_chunks == 27
        assert row.duration_ms == pytest.approx(6700.5)


async def test_update_sync_log_accepts_failed_with_errors(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = f"sync_fail_{uuid4().hex[:10]}"
    await store.create_sync_log(
        sync_id=sync_id,
        workspace_id=ws,
        connection_id=cid,
        connector_type="jira",
    )

    await store.update_sync_log(
        sync_id=sync_id,
        status="failed",
        errors=["boom: 500"],
        duration_ms=100.0,
    )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        assert row.status == "failed"
        assert row.errors == ["boom: 500"]
        assert row.documents_fetched == 0  # unchanged — we didn't pass it
