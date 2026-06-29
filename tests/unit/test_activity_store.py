"""Unit tests for ActivityStore — mocked async engine."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from metronix.storage.activity_pg import ActivityRow, ActivityStore


def _make_store() -> tuple[ActivityStore, MagicMock, AsyncMock]:
    engine = MagicMock()
    conn = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    engine.begin = MagicMock(return_value=ctx)
    return ActivityStore(engine), engine, conn


async def test_insert_builds_insert_statement() -> None:
    store, _engine, conn = _make_store()
    row = ActivityRow(
        workspace_id="ws",
        agent_id="ag",
        session_id=None,
        event_type="memory.created",
        event_data={"record_id": "r1"},
    )
    await store.insert(row)
    conn.execute.assert_called_once()
    _sql_obj, params = conn.execute.call_args[0]
    assert params["workspace_id"] == "ws"
    assert params["agent_id"] == "ag"
    assert params["event_type"] == "memory.created"


async def test_list_for_agent_applies_filters() -> None:
    store, _engine, conn = _make_store()
    result_mock = MagicMock()
    result_mock.mappings = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    conn.execute = AsyncMock(return_value=result_mock)
    await store.list_for_agent(
        workspace_id="ws",
        agent_id="ag",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=None,
        event_types=["memory.created"],
        session_id="sess-1",
        limit=10,
        offset=0,
    )
    assert conn.execute.call_count == 1
    sql_text = str(conn.execute.call_args[0][0])
    assert "workspace_id = :workspace_id" in sql_text
    assert "agent_id = :agent_id" in sql_text
    assert "created_at >= :since" in sql_text
    assert "event_type = ANY(:event_types)" in sql_text
    assert "session_id = :session_id" in sql_text


async def test_summary_groups_by_type_and_day() -> None:
    store, _engine, conn = _make_store()

    per_type_result = MagicMock()
    per_type_result.mappings = MagicMock(
        return_value=MagicMock(
            all=MagicMock(return_value=[{"event_type": "memory.created", "n": 5}])
        )
    )
    per_day_result = MagicMock()
    per_day_result.mappings = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[{"day": "2026-04-23", "n": 3}]))
    )

    conn.execute = AsyncMock(side_effect=[per_type_result, per_day_result])

    out = await store.summary_for_agent(
        workspace_id="ws",
        agent_id="ag",
        since=datetime(2026, 4, 1, tzinfo=UTC),
        until=datetime(2026, 4, 30, tzinfo=UTC),
    )
    assert out["counts_by_event_type"] == {"memory.created": 5}
    assert any(b["date"] == "2026-04-23" and b["total"] == 3 for b in out["counts_by_day"])
    assert out["total_events"] == 5


async def test_summary_zero_fills_days_in_window() -> None:
    """When no rows exist, still produce one bucket per calendar day."""
    store, _engine, conn = _make_store()

    empty_mappings = MagicMock(all=MagicMock(return_value=[]))
    empty_result = MagicMock()
    empty_result.mappings = MagicMock(return_value=empty_mappings)
    conn.execute = AsyncMock(return_value=empty_result)

    since = datetime(2026, 4, 20, 0, 0, tzinfo=UTC)
    until = datetime(2026, 4, 23, 0, 0, tzinfo=UTC)
    out = await store.summary_for_agent(
        workspace_id="ws",
        agent_id="ag",
        since=since,
        until=until,
    )
    days = [b["date"] for b in out["counts_by_day"]]
    assert days == ["2026-04-20", "2026-04-21", "2026-04-22"]
    assert all(b["total"] == 0 for b in out["counts_by_day"])
    assert out["total_events"] == 0
