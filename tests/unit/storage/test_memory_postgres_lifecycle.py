"""Unit tests for MemoryPostgresStore.update_lifecycle (MTRNIX-304)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metronix.core.models import MemoryStatus
from metronix.storage.memory_postgres import MemoryPostgresStore

_BASE_ROW = {
    "id": "mem001",
    "workspace_id": "ws1",
    "agent_id": "agent1",
    "scope": "per_agent",
    "source_type": "conversation",
    "content": "user prefers dark mode",
    "tags": ["preference"],
    "importance_score": 0.8,
    "ttl_expires_at": None,
    "content_hash": "abc123",
    "session_id": None,
    "metadata": {},
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    "status": "active",
    "freshness_score": 0.5,
    "superseded_by": None,
    "valid_from": None,
    "valid_until": None,
    "evidence_count": 0,
    "verification_state": None,
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


def _make_store() -> tuple[MemoryPostgresStore, MagicMock]:
    engine = MagicMock()
    return MemoryPostgresStore(engine), engine


class TestUpdateLifecycle:
    async def test_status_update_writes_returning_record(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        updated = dict(_BASE_ROW)
        updated["status"] = "stale"
        updated["freshness_score"] = 0.25
        result = MagicMock()
        result.first.return_value = _mock_row(updated)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.update_lifecycle(
            "ws1",
            "mem001",
            status=MemoryStatus.STALE,
            freshness_score=0.25,
        )

        assert out is not None
        assert out.status == MemoryStatus.STALE
        assert out.freshness_score == 0.25
        sql = str(conn.execute.call_args.args[0])
        assert "status = :status" in sql
        assert "freshness_score = :freshness_score" in sql
        assert "RETURNING" in sql
        params = conn.execute.call_args.args[1]
        assert params["ws"] == "ws1"
        assert params["status"] == "stale"

    async def test_evidence_count_and_verification_state(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        updated = dict(_BASE_ROW, evidence_count=3, verification_state="verified")
        result = MagicMock()
        result.first.return_value = _mock_row(updated)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.update_lifecycle(
            "ws1",
            "mem001",
            evidence_count=3,
            verification_state="verified",
        )

        assert out is not None
        assert out.evidence_count == 3
        assert out.verification_state == "verified"

    async def test_lifecycle_update_does_not_bump_updated_at(self) -> None:
        """MTRNIX-395: update_lifecycle must not touch ``updated_at``.

        It is the freshness clock FreshnessMonitor reads for STALE; bumping it
        on the Linker's evidence_count write made STALE unreachable. Only
        ``save()`` (a real content edit) may move ``updated_at``.
        """
        store, engine = _make_store()
        conn = AsyncMock()
        updated = dict(_BASE_ROW, evidence_count=5)
        result = MagicMock()
        result.first.return_value = _mock_row(updated)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.update_lifecycle("ws1", "mem001", evidence_count=5)

        sql = str(conn.execute.call_args.args[0])
        # ``updated_at`` may still appear in the RETURNING column list — what
        # must NOT happen is a SET write of it.
        assert "updated_at = :updated_at" not in sql
        assert "SET evidence_count = :evidence_count WHERE" in sql
        params = conn.execute.call_args.args[1]
        assert "updated_at" not in params

    async def test_bump_updated_at_flag_writes_updated_at(self) -> None:
        """MTRNIX-395: human curation opts back into the updated_at bump.

        ``resolve_review`` passes ``bump_updated_at=True`` so a kept record's
        freshness clock is refreshed and it does not immediately re-STALE.
        """
        store, engine = _make_store()
        conn = AsyncMock()
        updated = dict(_BASE_ROW, status="active")
        result = MagicMock()
        result.first.return_value = _mock_row(updated)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        await store.update_lifecycle(
            "ws1",
            "mem001",
            status=MemoryStatus.ACTIVE,
            bump_updated_at=True,
        )

        sql = str(conn.execute.call_args.args[0])
        assert "updated_at = :updated_at" in sql
        params = conn.execute.call_args.args[1]
        assert "updated_at" in params

    async def test_empty_update_falls_back_to_get(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        # No fields supplied → store.get() path is taken.
        result = MagicMock()
        result.first.return_value = _mock_row(_BASE_ROW)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.update_lifecycle("ws1", "mem001")

        assert out is not None
        sql = str(conn.execute.call_args.args[0])
        assert sql.strip().startswith("SELECT")

    async def test_not_found_returns_none(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.update_lifecycle("ws1", "missing", status=MemoryStatus.STALE)

        assert out is None

    async def test_append_tag_uses_idempotent_sql(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        updated = dict(_BASE_ROW, tags=["preference", "auto_curated"])
        result = MagicMock()
        result.first.return_value = _mock_row(updated)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.update_lifecycle("ws1", "mem001", append_tag="auto_curated")

        assert out is not None
        sql = str(conn.execute.call_args.args[0])
        assert "tags @> CAST(:tag_array AS jsonb)" in sql
        params = conn.execute.call_args.args[1]
        assert params["tag_array"] == '["auto_curated"]'

    async def test_superseded_by_empty_string_nullifies(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        updated = dict(_BASE_ROW, superseded_by=None)
        result = MagicMock()
        result.first.return_value = _mock_row(updated)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.update_lifecycle("ws1", "mem001", superseded_by="")

        assert out is not None
        sql = str(conn.execute.call_args.args[0])
        assert "superseded_by = NULL" in sql

    async def test_append_tags_batch_single_update(self) -> None:
        """The batch path must execute ONE UPDATE with SQL-side dedup."""
        store, engine = _make_store()
        conn = AsyncMock()
        updated = dict(_BASE_ROW, tags=["preference", "payment", "stripe"])
        result = MagicMock()
        result.first.return_value = _mock_row(updated)
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.update_lifecycle(
            "ws1",
            "mem001",
            append_tags=["payment", "stripe", "payment"],  # duplicate input
        )

        assert out is not None
        # Exactly one execute call — not one per tag.
        assert conn.execute.call_count == 1
        sql = str(conn.execute.call_args.args[0])
        # SQL-side dedup against the existing row's tags.
        assert "jsonb_array_elements_text" in sql
        assert "NOT tags @> jsonb_build_array(e)" in sql
        params = conn.execute.call_args.args[1]
        # Input list is also deduped client-side.
        import json as _json

        assert _json.loads(params["new_tags"]) == ["payment", "stripe"]
