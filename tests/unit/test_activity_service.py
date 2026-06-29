"""ActivityService — list + summary facade used by /activity routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from metronix.activity.service import ActivityService


@pytest.fixture
def store() -> AsyncMock:
    m = AsyncMock()
    m.list_for_agent = AsyncMock(return_value=[])
    m.summary_for_agent = AsyncMock(
        return_value={
            "total_events": 0,
            "counts_by_event_type": {},
            "counts_by_day": [],
        }
    )
    return m


async def test_list_has_more_true(store: AsyncMock) -> None:
    # Simulate store returning limit+1 rows (service asks for limit+1)
    store.list_for_agent = AsyncMock(return_value=[{"id": i} for i in range(11)])
    svc = ActivityService(store=store, workspace_id="ws")
    events, has_more = await svc.list_for_agent(
        agent_id="ag",
        since=None,
        until=None,
        event_types=None,
        session_id=None,
        limit=10,
        offset=0,
    )
    assert len(events) == 10
    assert has_more is True


async def test_list_has_more_false(store: AsyncMock) -> None:
    store.list_for_agent = AsyncMock(return_value=[{"id": i} for i in range(5)])
    svc = ActivityService(store=store, workspace_id="ws")
    events, has_more = await svc.list_for_agent(
        agent_id="ag",
        since=None,
        until=None,
        event_types=None,
        session_id=None,
        limit=10,
        offset=0,
    )
    assert len(events) == 5
    assert has_more is False


async def test_list_passes_workspace_and_filters(store: AsyncMock) -> None:
    svc = ActivityService(store=store, workspace_id="ws_main")
    await svc.list_for_agent(
        agent_id="ag",
        since=None,
        until=None,
        event_types=["memory.created", "tool.called"],
        session_id="s1",
        limit=25,
        offset=50,
    )
    kwargs = store.list_for_agent.await_args.kwargs
    assert kwargs["workspace_id"] == "ws_main"
    assert kwargs["agent_id"] == "ag"
    assert kwargs["event_types"] == ["memory.created", "tool.called"]
    assert kwargs["session_id"] == "s1"
    # service requests limit+1 to compute has_more
    assert kwargs["limit"] == 26
    assert kwargs["offset"] == 50


async def test_summary_period_parsing(store: AsyncMock) -> None:
    now = datetime(2026, 4, 23, 12, 0, tzinfo=UTC)
    svc = ActivityService(store=store, workspace_id="ws")
    out = await svc.summary_for_agent(agent_id="ag", period="7d", now=now)
    since = store.summary_for_agent.await_args.kwargs["since"]
    until = store.summary_for_agent.await_args.kwargs["until"]
    assert until == now
    assert since == now - timedelta(days=7)
    # response shape: period echoed + since/until ISO strings + spread of store result
    assert out["period"] == "7d"
    assert out["since"] == since.isoformat()
    assert out["until"] == until.isoformat()
    assert "counts_by_event_type" in out
    assert "counts_by_day" in out
    assert "total_events" in out


async def test_summary_invalid_period_raises(store: AsyncMock) -> None:
    svc = ActivityService(store=store, workspace_id="ws")
    with pytest.raises(ValueError, match="period"):
        await svc.summary_for_agent(agent_id="ag", period="bogus")


async def test_summary_accepts_all_valid_periods(store: AsyncMock) -> None:
    now = datetime(2026, 4, 23, 12, 0, tzinfo=UTC)
    svc = ActivityService(store=store, workspace_id="ws")
    for p in ("1d", "7d", "30d", "90d"):
        await svc.summary_for_agent(agent_id="ag", period=p, now=now)
