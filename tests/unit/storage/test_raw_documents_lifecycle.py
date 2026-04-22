"""Unit tests for PostgresStore.update_raw_document_lifecycle (MTRNIX-313).

Mock-based: mirrors the pattern in ``test_memory_postgres_lifecycle.py`` so
the suite runs without touching a real PostgreSQL. Workspace isolation is
verified by inspecting the SQL parameters passed to the engine — every UPDATE
must carry ``workspace_id`` in the WHERE clause, even when the caller only
supplies ``raw_doc_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import LifecycleStatus, RawDocument
from metatron.storage.postgres import PostgresStore

_BASE_ROW: dict[str, object] = {
    "id": "doc001",
    "workspace_id": "ws1",
    "connector_type": "confluence",
    "connection_id": "conn1",
    "source_id": "page-42",
    "title": "Example",
    "content": "body text",
    "url": "https://example.com/42",
    "author": "alice",
    "content_hash": "abc123",
    "metadata": {"space": "KB"},
    "source_role": "knowledge_base",
    "qdrant_synced": True,
    "graph_synced": True,
    "fetched_at": datetime(2026, 1, 1, tzinfo=UTC),
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    "status": "active",
    "freshness_score": 0.5,
    "superseded_by": None,
    "valid_until": None,
    "evidence_count": 0,
    "verification_state": None,
    "last_freshness_run_at": None,
}


def _mock_row(row_data: dict) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: row_data[k]
    mapping.get = lambda k, default=None: row_data.get(k, default)
    row = MagicMock()
    row._mapping = mapping
    return row


class _FakeCtx:
    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        pass


def _make_store() -> tuple[PostgresStore, MagicMock]:
    engine = MagicMock()
    store = PostgresStore.__new__(PostgresStore)
    store._engine = engine  # type: ignore[attr-defined]
    return store, engine


class TestRowToRawDocument:
    def test_full_row_round_trip(self) -> None:
        doc = PostgresStore._row_to_raw_document(_mock_row(_BASE_ROW))
        assert isinstance(doc, RawDocument)
        assert doc.id == "doc001"
        assert doc.workspace_id == "ws1"
        assert doc.status is LifecycleStatus.ACTIVE
        assert doc.freshness_score == 0.5
        assert doc.evidence_count == 0
        assert doc.verification_state is None
        assert doc.last_freshness_run_at is None

    def test_row_with_stale_status(self) -> None:
        row = dict(_BASE_ROW)
        row["status"] = "stale"
        row["freshness_score"] = 0.2
        row["evidence_count"] = 3
        row["verification_state"] = "llm_verified"
        doc = PostgresStore._row_to_raw_document(_mock_row(row))
        assert doc.status is LifecycleStatus.STALE
        assert doc.freshness_score == 0.2
        assert doc.evidence_count == 3
        assert doc.verification_state == "llm_verified"

    def test_row_with_invalid_status_falls_back_to_active(self) -> None:
        row = dict(_BASE_ROW)
        row["status"] = "nonexistent_state"
        doc = PostgresStore._row_to_raw_document(_mock_row(row))
        assert doc.status is LifecycleStatus.ACTIVE

    def test_row_with_string_metadata(self) -> None:
        row = dict(_BASE_ROW)
        row["metadata"] = '{"key": "val"}'
        doc = PostgresStore._row_to_raw_document(_mock_row(row))
        assert doc.metadata == {"key": "val"}


class TestGetRawDocumentById:
    async def test_returns_raw_document_when_row_exists(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.first.return_value = _mock_row(_BASE_ROW)
        conn.execute = AsyncMock(return_value=result)
        engine.begin.return_value = _FakeCtx(conn)

        doc = await store.get_raw_document_by_id("ws1", "doc001")
        assert doc is not None
        assert doc.id == "doc001"
        # Verify workspace_id was in the WHERE params.
        call_kwargs = conn.execute.await_args.args[1]
        assert call_kwargs["workspace_id"] == "ws1"
        assert call_kwargs["id"] == "doc001"

    async def test_returns_none_when_row_missing(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        conn.execute = AsyncMock(return_value=result)
        engine.begin.return_value = _FakeCtx(conn)

        doc = await store.get_raw_document_by_id("ws1", "missing")
        assert doc is None


class TestUpdateRawDocumentLifecycle:
    async def test_update_status_only_writes_single_field(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        engine.begin.return_value = _FakeCtx(conn)

        await store.update_raw_document_lifecycle(
            "ws1",
            "doc001",
            status=LifecycleStatus.STALE,
        )

        conn.execute.assert_awaited_once()
        sql = conn.execute.await_args.args[0].text
        params = conn.execute.await_args.args[1]
        assert "SET status = :status" in sql
        assert "freshness_score" not in sql
        assert params["status"] == "stale"
        assert params["workspace_id"] == "ws1"
        assert params["id"] == "doc001"

    async def test_update_all_fields(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        engine.begin.return_value = _FakeCtx(conn)
        now = datetime(2026, 1, 3, tzinfo=UTC)

        await store.update_raw_document_lifecycle(
            "ws1",
            "doc001",
            status=LifecycleStatus.SUPERSEDED,
            freshness_score=0.1,
            superseded_by="new-doc",
            evidence_count=3,
            verification_state="llm_verified",
            valid_until=now,
            last_freshness_run_at=now,
        )

        params = conn.execute.await_args.args[1]
        assert params["status"] == "superseded"
        assert params["freshness_score"] == 0.1
        assert params["superseded_by"] == "new-doc"
        assert params["evidence_count"] == 3
        assert params["verification_state"] == "llm_verified"
        assert params["valid_until"] == now
        assert params["last_freshness_run_at"] == now
        assert params["workspace_id"] == "ws1"

    async def test_noop_when_no_fields(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        engine.begin.return_value = _FakeCtx(conn)

        await store.update_raw_document_lifecycle("ws1", "doc001")

        conn.execute.assert_not_awaited()

    async def test_every_update_includes_workspace_id(self) -> None:
        """Workspace isolation is a hard invariant — the SQL must always
        carry workspace_id in the WHERE clause so a collision on ``id``
        across tenants cannot leak."""
        store, engine = _make_store()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        engine.begin.return_value = _FakeCtx(conn)

        await store.update_raw_document_lifecycle(
            "ws-a",
            "shared-id",
            status=LifecycleStatus.STALE,
        )

        sql = conn.execute.await_args.args[0].text
        assert "workspace_id = :workspace_id" in sql
        assert "AND id = :id" in sql
