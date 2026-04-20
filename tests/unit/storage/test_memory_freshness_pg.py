"""Unit tests for FreshnessPostgresStore (MTRNIX-304)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metatron.core.models import MachineEvent, ReviewEntry
from metatron.storage.memory_freshness_pg import FreshnessPostgresStore


def _make_store() -> tuple[FreshnessPostgresStore, MagicMock]:
    engine = MagicMock()
    return FreshnessPostgresStore(engine), engine


def _mock_row(row_data: dict) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: row_data[k]
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


class TestReviewEntries:
    async def test_save_review_entry_inserts_row(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        engine.begin.return_value = _FakeCtx(conn)
        entry = ReviewEntry(
            id="r1",
            workspace_id="ws1",
            record_id="m1",
            reason="possible_duplicate",
            related_record_id="m2",
            content="snippet",
            confidence=0.42,
            created_at=datetime(2026, 4, 20, tzinfo=UTC),
        )

        saved = await store.save_review_entry(entry)

        assert saved is entry
        sql = str(conn.execute.call_args.args[0])
        assert "INSERT INTO review_entries" in sql
        params = conn.execute.call_args.args[1]
        assert params["workspace_id"] == "ws1"
        assert params["reason"] == "possible_duplicate"

    async def test_list_review_entries_filters_by_record(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        row_data = {
            "id": "r1",
            "workspace_id": "ws1",
            "record_id": "m1",
            "reason": "possible_duplicate",
            "related_record_id": None,
            "content": "snippet",
            "confidence": 0.5,
            "created_at": datetime(2026, 4, 20, tzinfo=UTC),
        }
        result = MagicMock()
        result.fetchall.return_value = [_mock_row(row_data)]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        entries = await store.list_review_entries("ws1", record_id="m1")

        assert len(entries) == 1
        assert entries[0].reason == "possible_duplicate"
        sql = str(conn.execute.call_args.args[0])
        assert "record_id = :record_id" in sql
        params = conn.execute.call_args.args[1]
        assert params["ws"] == "ws1"
        assert params["record_id"] == "m1"

    async def test_find_review_entry_handles_null_related(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        out = await store.find_review_entry(
            "ws1", record_id="m1", reason="possible_duplicate"
        )

        assert out is None
        sql = str(conn.execute.call_args.args[0])
        assert "related_record_id IS NULL" in sql


class TestMachineEvents:
    async def test_save_machine_event_serializes_payload(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        engine.begin.return_value = _FakeCtx(conn)
        event = MachineEvent(
            id="e1",
            workspace_id="ws1",
            event_type="freshness_job_received",
            actor="freshness_worker",
            target_kind="memory_record",
            target_id="m1",
            payload={"event_type": "knowledge_changed"},
            created_at=datetime(2026, 4, 20, tzinfo=UTC),
        )

        saved = await store.save_machine_event(event)

        assert saved is event
        sql = str(conn.execute.call_args.args[0])
        assert "INSERT INTO machine_events" in sql
        assert "CAST(:payload AS jsonb)" in sql
        params = conn.execute.call_args.args[1]
        assert '"knowledge_changed"' in params["payload"]

    async def test_list_events_for_target_scopes_by_workspace(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        row = _mock_row(
            {
                "id": "e1",
                "workspace_id": "ws1",
                "event_type": "freshness_job_processed",
                "actor": "freshness_worker",
                "target_kind": "memory_record",
                "target_id": "m1",
                "payload": {"decision_action": "tag"},
                "created_at": datetime(2026, 4, 20, tzinfo=UTC),
            }
        )
        result = MagicMock()
        result.fetchall.return_value = [row]
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        events = await store.list_events_for_target("ws1", "memory_record", "m1")

        assert len(events) == 1
        assert events[0].event_type == "freshness_job_processed"
        params = conn.execute.call_args.args[1]
        assert params["ws"] == "ws1"
        assert params["target_kind"] == "memory_record"
        assert params["target_id"] == "m1"
