# MTRNIX-309 Sync Status Visibility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make connector sync reliably observable — connection status never gets stuck, every sync leaves a `sync_logs` row even when the background task dies, and the UI surfaces the per-sync result (fetched/new/chunks/errors) instead of only "Sync started".

**Architecture:** Three changes, two PRs. (Core) `trigger_sync` inserts a `status='running'` `sync_logs` row synchronously before spawning the background task — the background task then only UPDATEs. On API startup, a recovery pass converts any stuck `running` log row → `failed` and any `syncing` connection → `error`. (Core) `/api/v1/dashboard/sync-history` is extended with full per-sync fields and a `connection_id` filter. (UI) `ConnectionCard` polls the latest sync log and renders an inline summary.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async + sync), pydantic v2, pytest (asyncio_mode=auto) · TypeScript, React, @tanstack/react-query, Tailwind · atlassian-python-api ≥4 for Jira

**Spec:** `docs/superpowers/specs/2026-04-20-sync-status-visibility-design.md`

**Jira:** [MTRNIX-309](https://mtrnix.atlassian.net/browse/MTRNIX-309)

---

## Branch & Prerequisites

### Task 0: Create feature branch in metatron-core

**Files:** none

- [ ] **Step 1: Checkout fresh branch from develop**

```bash
cd ~/Projects/metatron/metatron_mvp/metatroncore
git checkout develop
git pull --ff-only
git checkout -b feature/MTRNIX-309-sync-visibility
```

Expected: new branch created from latest develop.

- [ ] **Step 2: Verify baseline tests pass**

```bash
make test
```

Expected: all tests green (baseline before any changes).

---

## Part 1 — Core: reliable sync_logs + recovery

### Task 1: Extend `sync-history` response schema with full fields

Current schema exposes only a subset (`id, source, title, started, duration_ms, records, status`) and has no `connection_id` filter. UI needs `connection_id`, `documents_fetched`, `documents_new`, `documents_updated`, `documents_skipped`, `qdrant_chunks`, `errors`, and the new `"running"` status.

**Files:**
- Modify: `src/metatron/api/routes/dashboard/sync.py:19-59` (endpoint + response model)
- Modify: `src/metatron/storage/dashboard_queries.py:104-144` (query function signature + SELECT)
- Test: `tests/unit/test_dashboard_sync.py` (new)

- [ ] **Step 1: Write failing test for new fields + `connection_id` filter**

Create `tests/unit/test_dashboard_sync.py`:

```python
"""Tests for dashboard sync-history query — filter + field coverage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from metatron.storage.dashboard_queries import get_sync_history_data
from metatron.storage.pg_connection import get_session
from metatron.storage.pg_models import SyncLogRow, WorkspaceRow, ConnectionRow


@pytest.fixture
def ws():
    """Seed a workspace for tests."""
    ws_id = f"ws_{datetime.now(UTC).timestamp():.0f}"
    with get_session() as s:
        s.add(WorkspaceRow(id=ws_id, name="test", slug=ws_id, is_default=False, is_active=True))
    yield ws_id


@pytest.fixture
def conn(ws):
    """Seed a connection for tests."""
    cid = f"conn_{datetime.now(UTC).timestamp():.0f}"
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
    _add_log(ws, conn, "sync_abc", "success")

    items = get_sync_history_data(ws, limit=10)

    assert len(items) == 1
    item = items[0]
    assert item["id"] == "sync_abc"
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
    _add_log(ws, conn, "sync_mine", "success")
    # Log for a different connection in the same workspace
    other_conn = "conn_other"
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
    _add_log(ws, other_conn, "sync_other", "success")

    items = get_sync_history_data(ws, limit=10, connection_id=conn)

    assert len(items) == 1
    assert items[0]["id"] == "sync_mine"


def test_get_sync_history_accepts_running_status(ws, conn):
    _add_log(ws, conn, "sync_running", "running", fetched=0, new=0, chunks=0)

    items = get_sync_history_data(ws, limit=10, connection_id=conn)

    assert items[0]["status"] == "running"
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/unit/test_dashboard_sync.py -v
```

Expected: 3 failures. Errors will mention missing `connection_id` keys or no `connection_id` parameter.

- [ ] **Step 3: Update `get_sync_history_data`**

Replace lines 104-144 of `src/metatron/storage/dashboard_queries.py`:

```python
def get_sync_history_data(
    workspace_id: str,
    limit: int,
    connection_id: str | None = None,
) -> list[dict]:
    """Get sync history for a workspace, optionally filtered by connection.

    Args:
        workspace_id: Workspace ID to query.
        limit: Maximum number of records to return.
        connection_id: Optional connection ID filter.

    Returns:
        List of sync history items with full sync-log fields.
    """
    try:
        with get_session() as session:
            stmt = (
                select(SyncLogRow)
                .where(SyncLogRow.workspace_id == workspace_id)
                .order_by(SyncLogRow.created_at.desc())
                .limit(limit)
            )
            if connection_id is not None:
                stmt = stmt.where(SyncLogRow.connection_id == connection_id)

            result = session.execute(stmt)
            rows = result.scalars().all()

            items = []
            for row in rows:
                items.append(
                    {
                        "id": row.id,
                        "connection_id": row.connection_id,
                        "connector_type": row.connector_type,
                        "source": row.connector_type,  # kept for back-compat
                        "title": row.source_title or f"{row.connector_type.capitalize()} Sync",
                        "started": row.created_at,
                        "duration_ms": row.duration_ms,
                        "records": row.qdrant_chunks,  # kept for back-compat
                        "documents_fetched": row.documents_fetched,
                        "documents_new": row.documents_new,
                        "documents_updated": row.documents_updated,
                        "documents_skipped": row.documents_skipped,
                        "qdrant_chunks": row.qdrant_chunks,
                        "errors": row.errors or [],
                        "status": row.status,
                    }
                )
            return items
    except Exception as e:
        logger.warning(
            "dashboard.sync_history.error",
            workspace_id=workspace_id,
            connection_id=connection_id,
            error=str(e),
        )
        return []
```

- [ ] **Step 4: Update endpoint response model + accept `connection_id`**

Replace lines 19-59 of `src/metatron/api/routes/dashboard/sync.py`:

```python
class SyncHistoryItem(BaseModel):
    """Single sync history entry."""

    id: str
    connection_id: str | None
    connector_type: str
    source: str
    title: str
    started: datetime
    duration_ms: float
    documents_fetched: int
    documents_new: int
    documents_updated: int
    documents_skipped: int
    qdrant_chunks: int
    records: int
    errors: list[str]
    status: Literal["success", "partial", "failed", "running"]


class SyncHistoryResponse(BaseModel):
    """Sync history response."""

    items: list[SyncHistoryItem]


@router.get("/sync-history", response_model=SyncHistoryResponse)
async def get_sync_history(
    workspace: Annotated[Workspace, Depends(get_valid_workspace)],
    limit: int = Query(default=10, ge=1, le=100),
    connection_id: str | None = Query(default=None),
) -> SyncHistoryResponse:
    """Get sync history for dashboard. Optionally filter by connection."""
    from metatron.storage.dashboard_queries import get_sync_history_data

    items = await asyncio.to_thread(
        get_sync_history_data,
        workspace.workspace_id,
        limit,
        connection_id,
    )

    return SyncHistoryResponse(items=items)
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/unit/test_dashboard_sync.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run typecheck + lint**

```bash
make typecheck && make lint
```

Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_dashboard_sync.py \
        src/metatron/storage/dashboard_queries.py \
        src/metatron/api/routes/dashboard/sync.py
git commit -m "feat(MTRNIX-309): expand sync-history with full fields + connection_id filter"
```

---

### Task 2: Add `PostgresStore.create_sync_log` + `update_sync_log` helpers

Centralize `sync_logs` writes in `PostgresStore`. `_run_connection_sync` can't stay with inline ORM — and we need both insert and partial update.

**Files:**
- Modify: `src/metatron/storage/postgres.py:507-560` (insert new helpers after `store_query_trace`)
- Test: `tests/unit/test_postgres_sync_logs.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_postgres_sync_logs.py`:

```python
"""Tests for PostgresStore.create_sync_log / update_sync_log helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from metatron.core.config import Settings
from metatron.storage.pg_connection import get_session
from metatron.storage.pg_models import SyncLogRow, WorkspaceRow, ConnectionRow
from metatron.storage.postgres import PostgresStore


@pytest.fixture
async def store():
    s = Settings()
    yield PostgresStore(s.postgres_dsn)


@pytest.fixture
def seeded_ids():
    ws_id = f"ws_{datetime.now(UTC).timestamp():.0f}"
    cid = f"conn_{datetime.now(UTC).timestamp():.0f}"
    with get_session() as s:
        s.add(WorkspaceRow(id=ws_id, name="t", slug=ws_id, is_default=False, is_active=True))
        s.add(
            ConnectionRow(
                id=cid,
                workspace_id=ws_id,
                connector_type="jira",
                name="T",
                config_encrypted=b"x",
                status="active",
                enabled=True,
            )
        )
    yield ws_id, cid


async def test_create_sync_log_inserts_running_row(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = "sync_test_create"

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
    sync_id = "sync_test_update"
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
    sync_id = "sync_test_fail"
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
```

- [ ] **Step 2: Run — expect failures (methods missing)**

```bash
pytest tests/unit/test_postgres_sync_logs.py -v
```

Expected: 3 failures, `AttributeError: 'PostgresStore' object has no attribute 'create_sync_log'`.

- [ ] **Step 3: Add helpers to PostgresStore**

Append after the existing `store_query_trace` method in `src/metatron/storage/postgres.py` (after line ~560, before any "# --- ___ ---" section marker — place after the observability section begins):

```python
    # --- Sync logs ---

    async def create_sync_log(
        self,
        sync_id: str,
        workspace_id: str,
        connection_id: str | None,
        connector_type: str,
    ) -> None:
        """Insert a `sync_logs` row with status='running'.

        Called synchronously from `trigger_sync` BEFORE the background task
        is scheduled, so that a record exists even if the task dies before
        reaching its `finally` block.
        """
        logger.info(
            "postgres.sync_log.create",
            sync_id=sync_id,
            workspace_id=workspace_id,
            connector_type=connector_type,
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO sync_logs "
                    "(id, workspace_id, connection_id, connector_type, status, "
                    " documents_fetched, documents_new, documents_updated, "
                    " documents_skipped, errors, duration_ms, source_title, "
                    " qdrant_chunks, created_at) "
                    "VALUES (:id, :ws, :conn, :ct, 'running', "
                    "        0, 0, 0, 0, '[]'::jsonb, 0, :title, 0, :now)"
                ),
                {
                    "id": sync_id,
                    "ws": workspace_id,
                    "conn": connection_id,
                    "ct": connector_type,
                    "title": f"{connector_type.capitalize()} Sync",
                    "now": datetime.now(UTC),
                },
            )

    async def update_sync_log(
        self,
        sync_id: str,
        status: str,
        documents_fetched: int | None = None,
        documents_new: int | None = None,
        documents_updated: int | None = None,
        documents_skipped: int | None = None,
        qdrant_chunks: int | None = None,
        errors: list[str] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Finalize a sync_logs row. Only non-None fields are updated."""
        logger.info("postgres.sync_log.update", sync_id=sync_id, status=status)

        set_parts = ["status = :status"]
        params: dict[str, Any] = {"id": sync_id, "status": status}

        if documents_fetched is not None:
            set_parts.append("documents_fetched = :df")
            params["df"] = documents_fetched
        if documents_new is not None:
            set_parts.append("documents_new = :dn")
            params["dn"] = documents_new
        if documents_updated is not None:
            set_parts.append("documents_updated = :du")
            params["du"] = documents_updated
        if documents_skipped is not None:
            set_parts.append("documents_skipped = :ds")
            params["ds"] = documents_skipped
        if qdrant_chunks is not None:
            set_parts.append("qdrant_chunks = :qc")
            params["qc"] = qdrant_chunks
        if errors is not None:
            set_parts.append("errors = CAST(:err AS jsonb)")
            params["err"] = json.dumps(errors)
        if duration_ms is not None:
            set_parts.append("duration_ms = :dur")
            params["dur"] = duration_ms

        async with self._engine.begin() as conn:
            await conn.execute(
                text(f"UPDATE sync_logs SET {', '.join(set_parts)} WHERE id = :id"),
                params,
            )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/unit/test_postgres_sync_logs.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_postgres_sync_logs.py src/metatron/storage/postgres.py
git commit -m "feat(MTRNIX-309): PostgresStore.create_sync_log / update_sync_log"
```

---

### Task 3: Refactor `_run_connection_sync` — initial row + UPDATE

**Files:**
- Modify: `src/metatron/api/routes/connections.py:543-601` (`trigger_sync`)
- Modify: `src/metatron/api/routes/connections.py:629-...` (`_run_connection_sync`)
- Test: `tests/unit/test_connections_sync.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_connections_sync.py`:

```python
"""Tests for _run_connection_sync — initial row + finalize pattern."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.api.routes.connections import _run_connection_sync
from metatron.core.events import EventBus
from metatron.storage.pg_connection import get_session
from metatron.storage.pg_models import SyncLogRow, WorkspaceRow, ConnectionRow
from metatron.storage.postgres import PostgresStore
from metatron.core.config import Settings
from metatron.core.models import Document


@pytest.fixture
async def store():
    yield PostgresStore(Settings().postgres_dsn)


@pytest.fixture
def seeded_ids():
    ws_id = f"ws_run_{datetime.now(UTC).timestamp():.0f}"
    cid = f"conn_run_{datetime.now(UTC).timestamp():.0f}"
    with get_session() as s:
        s.add(WorkspaceRow(id=ws_id, name="t", slug=ws_id, is_default=False, is_active=True))
        s.add(
            ConnectionRow(
                id=cid,
                workspace_id=ws_id,
                connector_type="jira",
                name="T",
                config_encrypted=b"x",
                status="syncing",
                enabled=True,
            )
        )
    yield ws_id, cid


async def test_run_connection_sync_finalizes_running_row_on_success(store, seeded_ids):
    ws, cid = seeded_ids
    sync_id = "sync_run_success"

    # Pre-insert the running row (simulates what trigger_sync did)
    await store.create_sync_log(sync_id, ws, cid, "jira")

    # Stub: connector returns 2 docs; ingest returns all-new
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
    sync_id = "sync_run_fail"
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
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/unit/test_connections_sync.py -v
```

Expected: failures because `_run_connection_sync` still has the old signature (no `sync_id` argument) and still writes `sync_logs` in `finally`.

- [ ] **Step 3: Update `trigger_sync` to pre-insert `sync_logs` row**

In `src/metatron/api/routes/connections.py`, around line 543 (`trigger_sync`), generate `sync_id` synchronously, insert the running row, then pass `sync_id` into the background task.

Replace the existing `trigger_sync` body (lines 543-601) with:

```python
@router.post("/{connection_id}/sync/")
async def trigger_sync(
    connection_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace_id: str | None = Query(None),
) -> dict[str, str]:
    """Trigger a manual sync for a DB-based connection.

    Writes a `sync_logs` row with status='running' SYNCHRONOUSLY before
    spawning the background task, so that a record exists even when the
    task is destroyed before reaching its finally block (API restart,
    CancelledError, hung LLM call). The background task then UPDATEs
    this row on completion or failure.
    """
    import uuid

    fernet_key = _get_fernet_key(request)
    store = _get_store(request)
    ws_id = _get_workspace_id(request, workspace_id)

    conn = await store.get_connection_decrypted(connection_id, fernet_key)
    if conn is None or conn["workspace_id"] != ws_id:
        raise HTTPException(status_code=404, detail="Connection not found")

    connector_type = conn["connector_type"]
    schema = CONNECTOR_SCHEMAS.get(connector_type)
    if not schema or schema.category != "connector":
        raise HTTPException(
            status_code=400,
            detail="Sync is only available for connectors, not channels",
        )

    if not conn.get("enabled", True):
        raise HTTPException(status_code=400, detail="Connection is disabled")

    # Mark connection as syncing
    await store.update_connection_status(connection_id, status="syncing")

    # Pre-insert a running sync_logs row so we always leave a trace, even
    # if the background task is destroyed before its finally block runs.
    sync_id = f"sync_{uuid.uuid4().hex[:12]}"
    try:
        await store.create_sync_log(
            sync_id=sync_id,
            workspace_id=ws_id,
            connection_id=connection_id,
            connector_type=connector_type,
        )
    except Exception as e:
        # Non-fatal — sync still runs, but we lose visibility for this attempt.
        logger.warning("sync.create_log.failed", connection_id=connection_id, error=str(e))

    pm = getattr(request.app.state, "plugin_manager", None)
    event_bus = pm.get_event_bus() if pm is not None else None

    background_tasks.add_task(
        _run_connection_sync,
        sync_id=sync_id,
        connection_id=connection_id,
        connector_type=connector_type,
        config=conn["config"],
        workspace_id=ws_id,
        store=store,
        event_bus=event_bus,
    )

    return {
        "status": "sync_started",
        "sync_id": sync_id,
        "connection_id": connection_id,
        "connector_type": connector_type,
    }
```

- [ ] **Step 4: Update `_run_connection_sync` signature + UPDATE instead of INSERT**

Replace the signature + body of `_run_connection_sync` (currently starts around line 629). The change is:

1. Add `sync_id: str` as the first kwarg (after `self`? no — it's a function, not method; just first arg after the `*`).
2. Remove the old `sync_id = f"sync_{uuid.uuid4().hex[:12]}"` line.
3. Replace the inline ORM `_write_sync_log` with a call to `store.update_sync_log(sync_id=sync_id, status=status, ...)`.

Full replacement body (keep all existing phase code between `try:` and `except:` unchanged except for the removed `sync_id =` line):

```python
async def _run_connection_sync(
    sync_id: str,
    connection_id: str,
    connector_type: str,
    config: dict[str, Any],
    workspace_id: str,
    store: PostgresStore,
    event_bus: EventBus | None = None,
) -> None:
    """Run sync for a DB-based connection. Async background task.

    Expects a `sync_logs` row with id=sync_id already inserted by
    `trigger_sync` with status='running'. Updates that row on
    completion, failure, or exception.
    """
    import asyncio
    import time
    from datetime import UTC, datetime

    from metatron.ingestion.pipeline import ingest_documents

    start_time = time.perf_counter()
    status = "failed"
    documents_fetched = 0
    documents_new = 0
    documents_updated = 0
    documents_skipped = 0
    qdrant_chunks = 0
    errors_list: list[str] = []

    logger.info(
        "sync.db_connection.started",
        sync_id=sync_id,
        connection_id=connection_id,
        connector_type=connector_type,
    )
    try:
        registry = _get_registry()
        connector = registry.create(connector_type)

        connection_obj = Connection(
            id=connection_id,
            workspace_id=workspace_id,
            connector_type=connector_type,
        )

        await connector.configure(connection_obj, config)

        from metatron.connectors.sync_state import SyncState

        sync_state = SyncState()
        since = sync_state.get_last_sync(workspace_id, connector_type)
        documents = await connector.fetch(workspace_id, since=since)
        documents_fetched = len(documents)

        logger.info(
            "sync.fetched",
            sync_id=sync_id,
            connector_type=connector_type,
            documents=documents_fetched,
        )

        upsert_result = None
        try:
            upsert_result = await store.upsert_raw_documents(
                workspace_id=workspace_id,
                documents=documents,
                connector_type=connector_type,
                connection_id=connection_id,
            )
            logger.info(
                "sync.raw_documents.persisted",
                new=upsert_result["new"],
                updated=upsert_result["updated"],
                unchanged=upsert_result["unchanged"],
            )
        except Exception as e:
            logger.warning("sync.raw_documents.error", error=str(e))

        if upsert_result and upsert_result.get("changed_source_ids"):
            changed_ids = set(upsert_result["changed_source_ids"])
            docs_to_ingest = [d for d in documents if d.source_id in changed_ids]
            logger.info(
                "sync.filtering_unchanged",
                total=len(documents),
                changed=len(docs_to_ingest),
                skipped=len(documents) - len(docs_to_ingest),
            )
        else:
            docs_to_ingest = documents

        if docs_to_ingest:
            result = await ingest_documents(
                docs_to_ingest,
                workspace_id,
                connector_type,
                source_role=connector.source_role,
                skip_graph=True,
            )
            documents_new = result.documents_new
            documents_updated = result.documents_updated
            documents_skipped = result.documents_skipped
            qdrant_chunks = result.documents_new + result.documents_updated

            if result.errors:
                errors_list = [_sanitize_error(str(e)) for e in result.errors[:10]]
                status = "partial" if result.documents_new > 0 else "failed"
            else:
                status = "success"

            try:
                all_source_ids = [d.source_id for d in documents if d.source_id]
                if all_source_ids:
                    await store.mark_documents_synced_by_source(
                        workspace_id=workspace_id,
                        connector_type=connector_type,
                        source_ids=all_source_ids,
                        target="qdrant",
                    )
            except Exception as e:
                logger.warning("sync.mark_synced.error", error=str(e))
        else:
            status = "success"

        try:
            from metatron.ingestion.pipeline import process_all_unsynced_graphs

            graph_result = await process_all_unsynced_graphs(workspace_id, store)
            logger.info(
                "sync.graph_processing.done",
                ok=graph_result["ok"],
                errors=graph_result["errors"],
            )
        except Exception as e:
            logger.warning("sync.graph_processing.error", error=str(e))

    except Exception as e:
        logger.error(
            "sync.db_connection.failed",
            sync_id=sync_id,
            connection_id=connection_id,
            error=str(e),
        )
        errors_list = [_sanitize_error(str(e))]
        status = "failed"

    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        final_conn_status = "active" if status == "success" else "error"
        error_msg = "; ".join(errors_list) if errors_list else None

        # Update sync_logs row (centralized helper)
        try:
            await store.update_sync_log(
                sync_id=sync_id,
                status=status,
                documents_fetched=documents_fetched,
                documents_new=documents_new,
                documents_updated=documents_updated,
                documents_skipped=documents_skipped,
                qdrant_chunks=qdrant_chunks,
                errors=errors_list,
                duration_ms=duration_ms,
            )
            logger.info("sync.logged", sync_id=sync_id, status=status, duration_ms=duration_ms)
        except Exception as e:
            logger.warning("sync.log_failed", sync_id=sync_id, error=str(e))

        # Update connection status
        try:
            await store.update_connection_status(
                connection_id,
                status=final_conn_status,
                error_message=error_msg,
                last_synced_at=datetime.now(UTC),
            )
        except Exception as e:
            logger.warning(
                "sync.status_update_failed",
                connection_id=connection_id,
                error=str(e),
            )

        if status in ("success", "partial"):
            try:
                from metatron.connectors.sync_state import SyncState

                sync_state = SyncState()
                sync_state.set_last_sync(workspace_id, connector_type)
            except Exception as e:
                logger.warning("sync.state_save.error", error=str(e))

        if event_bus is not None:
            try:
                from metatron.core.events import SYNC_COMPLETED

                await event_bus.emit(
                    SYNC_COMPLETED,
                    {
                        "sync_id": sync_id,
                        "workspace_id": workspace_id,
                        "connection_id": connection_id,
                        "connector_type": connector_type,
                        "status": status,
                    },
                )
            except Exception as e:
                logger.warning("sync.event_emit.failed", error=str(e))
```

(You can delete the now-unused `get_session` / `SyncLogRow` imports inside this function if any remain.)

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/unit/test_connections_sync.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Run full unit suite as regression check**

```bash
make lint && make typecheck && make test
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_connections_sync.py src/metatron/api/routes/connections.py
git commit -m "feat(MTRNIX-309): pre-insert running sync_logs row before background task"
```

---

### Task 4: Startup recovery module

**Files:**
- Create: `src/metatron/storage/recovery.py`
- Test: `tests/unit/test_sync_recovery.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_sync_recovery.py`:

```python
"""Tests for startup sync recovery — reset stuck `running` logs and `syncing` connections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from metatron.storage.pg_connection import get_engine, get_session
from metatron.storage.pg_models import SyncLogRow, WorkspaceRow, ConnectionRow
from metatron.storage.recovery import recover_interrupted_syncs


@pytest.fixture
def ws_and_conn():
    ws = f"ws_rec_{datetime.now(UTC).timestamp():.0f}"
    cid = f"conn_rec_{datetime.now(UTC).timestamp():.0f}"
    with get_session() as s:
        s.add(WorkspaceRow(id=ws, name="t", slug=ws, is_default=False, is_active=True))
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


def test_recovery_marks_running_logs_failed(ws_and_conn):
    ws, cid = ws_and_conn
    _seed_running_log(ws, cid, "sync_stuck", minutes_ago=10)

    result = recover_interrupted_syncs()

    assert result["sync_logs_reset"] >= 1
    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id="sync_stuck").first()
    assert row.status == "failed"
    assert any("interrupted" in e.lower() for e in row.errors)
    assert row.duration_ms > 0


def test_recovery_resets_syncing_connections(ws_and_conn):
    ws, cid = ws_and_conn

    result = recover_interrupted_syncs()

    assert result["connections_reset"] >= 1
    with get_session() as s:
        conn = s.query(ConnectionRow).filter_by(id=cid).first()
    assert conn.status == "error"
    assert conn.error_message is not None
    assert "interrupted" in conn.error_message.lower()


def test_recovery_is_idempotent(ws_and_conn):
    ws, cid = ws_and_conn
    _seed_running_log(ws, cid, "sync_idem")

    result1 = recover_interrupted_syncs()
    result2 = recover_interrupted_syncs()

    # Second run finds nothing to reset.
    assert result2["sync_logs_reset"] == 0
    assert result2["connections_reset"] == 0
    # Log is still failed — not double-mutated.
    with get_session() as s:
        row = s.query(SyncLogRow).filter_by(id="sync_idem").first()
    assert row.status == "failed"


def test_recovery_returns_zero_when_nothing_stuck():
    # Fresh run on a clean slate should return zeros without raising.
    result = recover_interrupted_syncs()

    assert "sync_logs_reset" in result
    assert "connections_reset" in result
    assert result["sync_logs_reset"] >= 0
    assert result["connections_reset"] >= 0
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/test_sync_recovery.py -v
```

Expected: `ModuleNotFoundError: No module named 'metatron.storage.recovery'`.

- [ ] **Step 3: Implement `recovery.py`**

Create `src/metatron/storage/recovery.py`:

```python
"""Startup recovery for interrupted syncs.

If the API is killed mid-sync (restart, SIGKILL, CancelledError), the
background `_run_connection_sync` task never reaches its finally block.
This leaves:
  - `sync_logs` rows with status='running' forever
  - `connections` rows with status='syncing' forever (blocking the UI Sync button)

`recover_interrupted_syncs()` is called once in the API lifespan (after
migrations, before serving) and flips both back to a terminal error state.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import text

from metatron.storage.pg_connection import get_session

logger = structlog.get_logger()


_INTERRUPTED_MSG = "Sync interrupted (API restart). Please retry."


def recover_interrupted_syncs() -> dict[str, int]:
    """Reset any stuck `running` sync_logs and `syncing` connections.

    Returns:
        {"sync_logs_reset": N, "connections_reset": M}
    """
    result = {"sync_logs_reset": 0, "connections_reset": 0}

    try:
        with get_session() as session:
            now = datetime.now(UTC)

            # 1) sync_logs.status='running' → 'failed'
            sync_logs_rows = session.execute(
                text(
                    "UPDATE sync_logs SET "
                    "  status = 'failed', "
                    "  errors = '[\"" + _INTERRUPTED_MSG.replace('"', '\\\"') + "\"]'::jsonb, "
                    "  duration_ms = EXTRACT(EPOCH FROM (:now - created_at)) * 1000 "
                    "WHERE status = 'running' "
                    "RETURNING id"
                ),
                {"now": now},
            )
            result["sync_logs_reset"] = len(sync_logs_rows.fetchall())

            # 2) connections.status='syncing' → 'error'
            conn_rows = session.execute(
                text(
                    "UPDATE connections SET "
                    "  status = 'error', "
                    "  error_message = :msg "
                    "WHERE status = 'syncing' "
                    "RETURNING id"
                ),
                {"msg": _INTERRUPTED_MSG},
            )
            result["connections_reset"] = len(conn_rows.fetchall())

        logger.info(
            "sync.recovery.done",
            sync_logs_reset=result["sync_logs_reset"],
            connections_reset=result["connections_reset"],
        )
    except Exception as exc:
        logger.warning("sync.recovery.failed", error=str(exc))

    return result
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/unit/test_sync_recovery.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_sync_recovery.py src/metatron/storage/recovery.py
git commit -m "feat(MTRNIX-309): startup recovery for stuck sync_logs and connections"
```

---

### Task 5: Wire recovery into lifespan

**Files:**
- Modify: `src/metatron/api/app.py:76-109` (lifespan, after migrations)
- Test: integration via manual smoke (unit test for `recover_interrupted_syncs` exists in Task 4)

- [ ] **Step 1: Add recovery call in lifespan**

In `src/metatron/api/app.py`, just after the `migrate_env_to_db` block (around line 109, before "Shared DB engine" section), add:

```python
    # Recover from any syncs interrupted by a previous shutdown.
    # Reset `sync_logs.running` → `failed` and `connections.syncing` → `error`.
    try:
        import asyncio as _asyncio

        from metatron.storage.recovery import recover_interrupted_syncs

        rec = await _asyncio.to_thread(recover_interrupted_syncs)
        if rec["sync_logs_reset"] or rec["connections_reset"]:
            logger.info(
                "sync.recovery.applied",
                sync_logs_reset=rec["sync_logs_reset"],
                connections_reset=rec["connections_reset"],
            )
    except Exception as exc:
        logger.warning("sync.recovery.startup_failed", error=str(exc))
```

- [ ] **Step 2: Smoke — start API, confirm stuck connections reset**

Before Task 5 was merged the local stack has 1 stuck connection (Confluence). After restart:

```bash
# In one terminal:
pkill -f "python -m metatron" || true
make dev

# In another terminal, wait for startup log:
#   [info] sync.recovery.applied sync_logs_reset=0 connections_reset=1

# Confirm:
python3 -c "
from metatron.storage.pg_connection import get_session
from sqlalchemy import text
with get_session() as s:
    for r in s.execute(text(\"SELECT id, status FROM connections\")).fetchall():
        print(r)
"
```

Expected: no connection has `status='syncing'`.

- [ ] **Step 3: Run full test suite**

```bash
make lint && make typecheck && make test
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/metatron/api/app.py
git commit -m "feat(MTRNIX-309): recover interrupted syncs on API startup"
```

---

### Task 6: Push & open core PR

- [ ] **Step 1: Push branch**

```bash
cd ~/Projects/metatron/metatron_mvp/metatroncore
git push -u origin feature/MTRNIX-309-sync-visibility
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base develop \
  --title "feat(MTRNIX-309): reliable sync_logs + status recovery" \
  --body "$(cat <<'EOF'
## Summary
- Pre-insert `sync_logs` row with `status='running'` before scheduling the background sync task, so every sync attempt leaves a trace even when killed mid-run
- Add startup recovery: `running` sync_logs → `failed`, `syncing` connections → `error` (unblocks the UI Sync button when a previous run was interrupted)
- Extend `GET /api/v1/dashboard/sync-history` with full fields (`documents_fetched/new/updated/skipped`, `qdrant_chunks`, `errors`, `connection_id`) and a `connection_id` filter so the UI can show per-connection history

## Test plan
- [ ] `make lint && make typecheck && make test` green
- [ ] Manual: trigger Jira sync, observe `sync_logs` row created synchronously with status=running, then updated to success on completion
- [ ] Manual: kill API mid-sync, restart — startup logs show `sync.recovery.applied`, connection no longer stuck in `syncing`
- [ ] Manual: new `GET /api/v1/dashboard/sync-history?connection_id=<id>` returns only that connection's rows, with richer payload

Ticket: https://mtrnix.atlassian.net/browse/MTRNIX-309
EOF
)"
```

- [ ] **Step 3: Hold for review**

Wait for reviewer approval before continuing to Part 2 (UI). The UI changes depend on the new endpoint response shape.

---

## Part 2 — UI: surface sync result in `metatronui-kb`

### Task 7: Create feature branch in metatron-ui

**Files:** none

- [ ] **Step 1: Checkout branch**

```bash
cd ~/Projects/metatron/metatron_mvp/metatronui
git checkout develop
git pull --ff-only
git checkout -b feature/MTRNIX-309-sync-visibility
```

---

### Task 8: Add SyncLog types + API functions

**Files:**
- Modify: `metatronui-kb/src/api/connections.ts` (append)

- [ ] **Step 1: Append types + fetch functions**

At the end of `metatronui-kb/src/api/connections.ts`, add:

```ts
// --- Sync logs ---

export type SyncLogStatus = 'success' | 'partial' | 'failed' | 'running';

export interface SyncLog {
  id: string;
  connection_id: string | null;
  connector_type: string;
  title: string;
  started: string;
  duration_ms: number;
  documents_fetched: number;
  documents_new: number;
  documents_updated: number;
  documents_skipped: number;
  qdrant_chunks: number;
  errors: string[];
  status: SyncLogStatus;
}

export function listSyncLogs(
  workspaceId: string,
  connectionId: string,
  limit = 10,
): Promise<SyncLog[]> {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    connection_id: connectionId,
    limit: String(limit),
  });
  return apiFetch<{ items: SyncLog[] }>(
    `/api/v1/dashboard/sync-history?${params}`,
  ).then((r) => r.items);
}

export function getLatestSyncLog(
  workspaceId: string,
  connectionId: string,
): Promise<SyncLog | null> {
  return listSyncLogs(workspaceId, connectionId, 1).then(
    (items) => items[0] ?? null,
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd ~/Projects/metatron/metatron_mvp/metatronui/metatronui-kb
npm run typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/metatron/metatron_mvp/metatronui
git add metatronui-kb/src/api/connections.ts
git commit -m "feat(MTRNIX-309): SyncLog type + listSyncLogs / getLatestSyncLog"
```

---

### Task 9: Add `useLatestSyncLog` hook with polling

**Files:**
- Modify: `metatronui-kb/src/hooks/useConnections.ts` (append hook)

- [ ] **Step 1: Append hook**

At the end of `metatronui-kb/src/hooks/useConnections.ts`, add:

```ts
import { getLatestSyncLog, listSyncLogs } from '@/api/connections';

export function useLatestSyncLog(
  connectionId: string | undefined,
  connectionStatus: string | undefined,
) {
  const workspaceId = useActiveWorkspaceId();
  return useQuery({
    queryKey: ['connections', 'latest-sync-log', workspaceId, connectionId],
    queryFn: () => {
      if (!workspaceId) throw new Error('No workspace selected');
      if (!connectionId) throw new Error('No connection id');
      return getLatestSyncLog(workspaceId, connectionId);
    },
    enabled: !!workspaceId && !!connectionId,
    // Poll every 5s while the connection is actively syncing;
    // otherwise refresh at the normal 15s cadence used elsewhere.
    refetchInterval: connectionStatus === 'syncing' ? 5_000 : 15_000,
  });
}

export function useSyncHistory(connectionId: string | undefined) {
  const workspaceId = useActiveWorkspaceId();
  return useQuery({
    queryKey: ['connections', 'sync-history', workspaceId, connectionId],
    queryFn: () => {
      if (!workspaceId) throw new Error('No workspace selected');
      if (!connectionId) throw new Error('No connection id');
      return listSyncLogs(workspaceId, connectionId, 10);
    },
    enabled: !!workspaceId && !!connectionId,
  });
}
```

Also update the top-of-file imports if `getLatestSyncLog`/`listSyncLogs` weren't already importable from the same module — the existing `@/api/connections` import list is fine to extend.

- [ ] **Step 2: Typecheck**

```bash
npm run typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add metatronui-kb/src/hooks/useConnections.ts
git commit -m "feat(MTRNIX-309): useLatestSyncLog + useSyncHistory react-query hooks"
```

---

### Task 10: Render inline sync summary in `ConnectionCard`

**Files:**
- Modify: `metatronui-kb/src/components/sources/ConnectionCard.tsx`

- [ ] **Step 1: Import hook + helpers**

In `ConnectionCard.tsx` near the other `useConnections` imports (around line 17), add `useLatestSyncLog`. Near other `lucide-react` icon imports add `CheckCircle2`, `XCircle`, `Loader2` (if not present).

- [ ] **Step 2: Fetch the latest sync log + render summary**

Inside the `ConnectionCard` component body, after existing `syncMutation` / `testMutation` setup and before the `return (`, add:

```tsx
const { data: lastSync } = useLatestSyncLog(connection.id, connection.status);

function renderSyncSummary() {
  if (!lastSync) return null;

  const duration = (lastSync.duration_ms / 1000).toFixed(1);

  if (lastSync.status === 'running') {
    return (
      <div className="mt-2 flex items-center gap-1.5 text-xs text-accent">
        <Loader2 size={12} className="animate-spin" />
        <span>Running… (started {relativeTime(lastSync.started)})</span>
      </div>
    );
  }

  if (lastSync.status === 'failed') {
    const err = lastSync.errors[0] ?? 'Unknown error';
    return (
      <div className="mt-2 flex items-start gap-1.5 text-xs text-error">
        <XCircle size={12} className="mt-0.5 shrink-0" />
        <span className="truncate" title={err}>
          Last sync failed: {err}
        </span>
      </div>
    );
  }

  // success | partial
  const Icon = lastSync.status === 'partial' ? AlertCircle : CheckCircle2;
  const color = lastSync.status === 'partial' ? 'text-warning' : 'text-success';

  return (
    <div className={`mt-2 flex items-center gap-1.5 text-xs ${color}`}>
      <Icon size={12} />
      <span>
        Last sync: {lastSync.documents_fetched} fetched · {lastSync.documents_new} new · {lastSync.qdrant_chunks} chunks · {duration}s
      </span>
    </div>
  );
}
```

- [ ] **Step 3: Insert the summary into the card JSX**

Place `{renderSyncSummary()}` right after the existing "Synced N ago" block (around line 167-170 of the current file, inside `<div className="mt-3 flex items-center gap-3 text-xs text-text-dim">...</div>`). Concretely, after that closing `</div>`, add:

```tsx
{renderSyncSummary()}
```

- [ ] **Step 4: Manual smoke**

```bash
cd ~/Projects/metatron/metatron_mvp/metatronui
npm run dev
```

- Open the Sources page.
- Confirm each connection card shows a "Last sync: …" line reflecting its most recent run.
- Trigger Sync — the line should flip to "Running…" within ~5s.
- When sync finishes — the line should update to the success/fail summary.

- [ ] **Step 5: Commit**

```bash
git add metatronui-kb/src/components/sources/ConnectionCard.tsx
git commit -m "feat(MTRNIX-309): inline last-sync summary on connection card"
```

---

### Task 11: Push & open UI PR

- [ ] **Step 1: Push**

```bash
git push -u origin feature/MTRNIX-309-sync-visibility
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base develop \
  --title "feat(MTRNIX-309): show sync result on connection card" \
  --body "$(cat <<'EOF'
## Summary
- Add `SyncLog` type + `getLatestSyncLog` / `listSyncLogs` API clients against the now-expanded `/api/v1/dashboard/sync-history` endpoint (connection_id filter, full sync fields)
- Add `useLatestSyncLog` hook that polls every 5s while `connection.status==='syncing'`, then 15s thereafter
- Render an inline "Last sync: N fetched · M new · K chunks · T.Ts" line on `ConnectionCard` — replaces the previous experience where only a generic "Synced N ago" was visible

Closes the "UI doesn't show the real sync result" half of MTRNIX-309. Depends on the metatron-core PR (new response fields + `connection_id` query param).

## Test plan
- [ ] `npm run typecheck` green
- [ ] Manual: card shows running → success transition on real sync
- [ ] Manual: card shows failure + error on forced bad-token sync
- [ ] Manual: after `running` → `failed` recovery (kill API mid-sync, restart), card shows "Last sync failed: Sync interrupted (API restart)"

Ticket: https://mtrnix.atlassian.net/browse/MTRNIX-309
EOF
)"
```

---

## Self-Review Coverage Matrix

| Spec item | Plan task(s) |
|---|---|
| Bug A: recovery on startup | T4 (module), T5 (lifespan wiring) |
| Bug A: Confluence connection cleared automatically | T5 smoke step |
| Bug B: pre-insert running row | T2 (helpers), T3 (trigger_sync refactor) |
| Bug B: centralize sync_logs writes in PostgresStore | T2 |
| Bug B: UPDATE in finally instead of INSERT | T3 |
| Bug C: extend response with full fields + connection_id filter | T1 |
| Bug C: SyncLog type + fetch functions | T8 |
| Bug C: polling hook | T9 |
| Bug C: inline card summary | T10 |
| Non-goal: Phase 4 hang fix | not in this plan (spec explicit non-goal) |
| Non-goal: watchdog | not in this plan (spec explicit non-goal) |
| Open question: verify Qdrant chunks match PG `qdrant_synced` | defer — the existing `qdrant_chunks` field on sync_logs is the source of truth the UI needs; a separate sanity check is out of scope and can be done manually during PR review |

## Notes for executors

- All three databases (Postgres, Qdrant, Neo4j) are assumed already running locally. No docker-compose changes required.
- `asyncio_mode = "auto"` is already set in `pyproject.toml`; tests do not need `@pytest.mark.asyncio`.
- The sync_logs.status column is `String(32)` — no migration needed to accept the new `'running'` literal.
- The core PR must merge first so the UI has the new endpoint shape available on its dev server.
