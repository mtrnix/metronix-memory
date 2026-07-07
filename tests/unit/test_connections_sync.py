"""Tests for _run_connection_sync — initial row + finalize pattern."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text

from metronix.connectors.connection_sync import run_connection_sync
from metronix.core.config import Settings
from metronix.core.models import Document, SyncResult
from metronix.storage.pg_connection import get_session
from metronix.storage.pg_models import ConnectionRow, SyncLogRow
from metronix.storage.postgres import PostgresStore


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


async def test_run_connection_sync_failed_when_fetch_errors_and_zero_docs(store, seeded_ids):
    """#322: a connector that surfaces ``fetch_errors`` and returns 0 docs must
    NOT be painted as ``status=success · 0 fetched``. The Admin Console shows
    ``status=failed`` + populated ``errors`` so the operator learns why
    nothing was fetched (e.g. a malformed org/repos URL on the GitHub
    connector). Without this, sync_logs ends up ``success``/``errors=[]`` —
    the silent-empty-success UX bug from #322."""
    ws, cid = seeded_ids
    sync_id = f"sync_fetch_errors_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[])
    # Connector surfaces non-transient per-repo failures (e.g. 404s on a
    # malformed org/repos URL) for the orchestrator to surface (#322).
    fake_connector.fetch_errors = [
        (
            "github: repository 'https://github.com/mtrnix/metronix-memory' "
            "failed to resolve: 404 Not Found"
        ),
    ]

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with (
        patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=_empty_ingest_result()),
        ),
        patch(
            "metronix.ingestion.pipeline.process_all_unsynced_graphs",
            AsyncMock(return_value={"ok": 0, "errors": 0}),
        ),
    ):
        await run_connection_sync(
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
        assert row.status == "failed", (
            f"status should be 'failed' for a 0-doc + fetch_errors sync, got {row.status!r}"
        )
        assert any("failed to resolve" in e for e in row.errors), (
            f"fetch_errors should surface in sync_log.errors, got {row.errors!r}"
        )
        assert row.documents_fetched == 0
        # A failed sync must not advance the cursor (consistent with the existing
        # failure-cursor invariant).
        assert conn.status == "error"


async def test_run_connection_sync_partial_when_fetch_errors_and_some_docs(store, seeded_ids):
    """#322: when ``fetch_errors`` is non-empty AND the connector still
    produced (and ingested) docs, the status is ``partial`` over ``success``."""
    ws, cid = seeded_ids
    sync_id = f"sync_fetch_errors_partial_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    doc = Document(
        source_type="jira",
        source_id="J-1",
        url="",
        workspace_id=ws,
        title="t",
        content="c",
        author="a",
        metadata={},
    )
    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[doc])
    fake_connector.fetch_errors = ["github: repository 'bad' failed to resolve: 404 Not Found"]

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    fake_ingest_result = MagicMock(
        documents_new=1,
        documents_updated=0,
        documents_skipped=0,
        errors=[],
    )
    with (
        patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=fake_ingest_result),
        ),
        patch(
            "metronix.ingestion.pipeline.process_all_unsynced_graphs",
            AsyncMock(return_value={"ok": 0, "errors": 0}),
        ),
    ):
        await run_connection_sync(
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
        assert row.status == "partial", (
            f"status should be 'partial' for a 1-doc + fetch_errors sync, got {row.status!r}"
        )
        assert any("failed to resolve" in e for e in row.errors), (
            f"fetch_errors should surface in sync_log.errors, got {row.errors!r}"
        )


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
        patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=fake_ingest_result),
        ),
        patch(
            "metronix.ingestion.pipeline.process_all_unsynced_graphs",
            AsyncMock(return_value={"ok": 1, "errors": 0}),
        ),
    ):
        await run_connection_sync(
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

    with patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry):
        await run_connection_sync(
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


async def test_run_connection_sync_failed_does_not_advance_cursor(store, seeded_ids):
    """Regression for PROJ-332 B1: failed sync must NOT move last_synced_at.

    Without the guard, the cursor advances unconditionally in the finally
    block — documents updated between the last good sync and the failure
    are then filtered out on next sync (silent data loss).

    Also tightens the failure path: asserts that the *seeded* exception
    message reaches the sync_logs row and the connection.error_message —
    otherwise the test would pass for any internal collaborator failure,
    not just the one we injected.
    """
    ws, cid = seeded_ids
    sync_id = f"sync_fail_cursor_{uuid4().hex[:10]}"

    # Seed an existing cursor — sync_id_prev "successful" — on the connection.
    prior_cursor = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    with get_session() as s:
        s.query(ConnectionRow).filter_by(id=cid).update({"last_synced_at": prior_cursor})

    await store.create_sync_log(sync_id, ws, cid, "jira")

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(side_effect=RuntimeError("transient network blip"))

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry):
        await run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            last_synced_at=prior_cursor,
        )

    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id=sync_id).first()
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
        # The exception we seeded must surface end-to-end (tightens the test
        # so it can't pass for some unrelated unmocked-collaborator failure).
        assert any("transient network blip" in e for e in row.errors), (
            f"expected seeded error message in sync_log.errors, got {row.errors!r}"
        )
        assert "transient network blip" in (conn.error_message or "")
        # Cursor must NOT have advanced.
        assert conn.status == "error"
        stored = conn.last_synced_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        assert stored == prior_cursor, (
            f"failed sync MUST NOT advance last_synced_at — was {prior_cursor!r}, "
            f"now {conn.last_synced_at!r}"
        )


async def test_run_connection_sync_force_full_failed_does_not_advance_cursor(store, seeded_ids):
    """force_full=True + failure: cursor must still NOT advance (per docstring)."""
    ws, cid = seeded_ids
    sync_id = f"sync_force_fail_{uuid4().hex[:10]}"

    prior_cursor = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    with get_session() as s:
        s.query(ConnectionRow).filter_by(id=cid).update({"last_synced_at": prior_cursor})
    await store.create_sync_log(sync_id, ws, cid, "jira")

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(side_effect=RuntimeError("forced full boom"))

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry):
        await run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            force_full=True,
            last_synced_at=prior_cursor,
        )

    with get_session() as s:
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
        assert conn.status == "error"
        stored = conn.last_synced_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        assert stored == prior_cursor


async def test_run_connection_sync_success_advances_cursor_past_prior(store, seeded_ids):
    """Positive path: a successful sync advances the cursor strictly past the prior.

    Pins the success branch behaviour — earlier tests verified `since` was
    forwarded but not that the cursor actually advanced.
    """
    ws, cid = seeded_ids
    sync_id = f"sync_advance_{uuid4().hex[:10]}"

    prior_cursor = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    with get_session() as s:
        s.query(ConnectionRow).filter_by(id=cid).update({"last_synced_at": prior_cursor})
    await store.create_sync_log(sync_id, ws, cid, "jira")

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[])

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with (
        patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=_empty_ingest_result()),
        ),
        patch(
            "metronix.ingestion.pipeline.process_all_unsynced_graphs",
            AsyncMock(return_value={"ok": 0, "errors": 0}),
        ),
    ):
        await run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            last_synced_at=prior_cursor,
        )

    with get_session() as s:
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
        assert conn.status == "active"
        stored = conn.last_synced_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=UTC)
        assert stored > prior_cursor, (
            f"successful sync must advance cursor past prior {prior_cursor!r}, got {stored!r}"
        )
        # And the stamp is bounded above by now() — sanity check that we are
        # using fetch_started_at (captured at function entry), not something
        # in the far future.
        assert stored <= datetime.now(UTC), f"cursor stamp must be <= now, got {stored!r}"


# ---------------------------------------------------------------------------
# force_full flag (PROJ-332)
# ---------------------------------------------------------------------------


def _empty_ingest_result() -> SyncResult:
    """Real SyncResult — fails fast if the dataclass shape drifts."""
    return SyncResult(
        documents_new=0,
        documents_updated=0,
        documents_skipped=0,
        errors=[],
    )


async def test_run_connection_sync_force_full_bypasses_cursor(store, seeded_ids):
    """force_full=True passes since=None even when PG has a stale cursor."""
    ws, cid = seeded_ids
    sync_id = f"sync_force_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    stale_cursor = datetime(2099, 1, 1, tzinfo=UTC)

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[])

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with (
        patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=_empty_ingest_result()),
        ),
    ):
        await run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            force_full=True,
            last_synced_at=stale_cursor,
        )

    fake_connector.fetch.assert_awaited_once()
    assert fake_connector.fetch.await_args.kwargs.get("since") is None, (
        f"force_full=True must pass since=None, got "
        f"{fake_connector.fetch.await_args.kwargs.get('since')!r}"
    )


async def test_run_connection_sync_default_uses_pg_cursor(store, seeded_ids):
    """force_full=False (default) reads cursor from last_synced_at param (PG)."""
    ws, cid = seeded_ids
    sync_id = f"sync_default_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    cursor = datetime(2026, 5, 1, tzinfo=UTC)

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[])

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with (
        patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=_empty_ingest_result()),
        ),
    ):
        await run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            last_synced_at=cursor,
        )

    fake_connector.fetch.assert_awaited_once()
    assert fake_connector.fetch.await_args.kwargs.get("since") == cursor


async def test_run_connection_sync_null_cursor_means_full_fetch(store, seeded_ids):
    """Freshly-created connection has last_synced_at=NULL → since=None → full fetch."""
    ws, cid = seeded_ids
    sync_id = f"sync_fresh_{uuid4().hex[:10]}"
    await store.create_sync_log(sync_id, ws, cid, "jira")

    fake_connector = MagicMock()
    fake_connector.source_role = "task_tracker"
    fake_connector.configure = AsyncMock()
    fake_connector.fetch = AsyncMock(return_value=[])

    fake_registry = MagicMock()
    fake_registry.create.return_value = fake_connector

    with (
        patch("metronix.connectors.connection_sync.get_registry", return_value=fake_registry),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            AsyncMock(return_value=_empty_ingest_result()),
        ),
    ):
        await run_connection_sync(
            sync_id=sync_id,
            connection_id=cid,
            connector_type="jira",
            config={"url": "http://x", "username": "u", "api_token": "t", "project_key": "P"},
            workspace_id=ws,
            store=store,
            event_bus=None,
            last_synced_at=None,  # explicit: never synced before
        )

    fake_connector.fetch.assert_awaited_once()
    assert fake_connector.fetch.await_args.kwargs.get("since") is None


# ---------------------------------------------------------------------------
# Concurrent-sync guard (PROJ-332)
# ---------------------------------------------------------------------------


async def test_trigger_sync_returns_409_when_connection_is_syncing(seeded_ids):
    """A POST /sync/ against a connection with status='syncing' returns 409.

    Best-effort guard (racy — see route comment). Verifies the common case:
    operator hits the button twice in a row, second hit is rejected.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from metronix.api.routes.connections import router as connections_router

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
