"""Routes /api/v1/agents/{id}/activity and /activity/summary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.auth.dependencies import get_current_user
from metronix.core.config import Settings
from metronix.core.models import Role, User


def _make_viewer() -> User:
    return User(
        id="u_test",
        username="tester",
        email="t@example.com",
        role=Role.VIEWER,
        workspace_ids=["default"],
    )


def _client(
    *,
    agent_exists: bool = True,
    activity_rows: list[dict[str, Any]] | None = None,
    has_more: bool = False,
) -> tuple[TestClient, MagicMock, MagicMock]:
    app = create_app(Settings(AUTH_ENABLED=False))

    reg = MagicMock()
    reg.workspace_id = "default"
    if agent_exists:
        rec = MagicMock()
        rec.id = "ag_1"
        rec.workspace_id = "default"
        reg.get_agent = AsyncMock(return_value=rec)
    else:
        from metronix.agents.service import AgentNotFoundError

        reg.get_agent = AsyncMock(side_effect=AgentNotFoundError("nope"))

    act = MagicMock()
    act.list_for_agent = AsyncMock(return_value=(activity_rows or [], has_more))
    act.summary_for_agent = AsyncMock(
        return_value={
            "period": "7d",
            "since": "2026-04-16T00:00:00+00:00",
            "until": "2026-04-23T00:00:00+00:00",
            "total_events": 0,
            "counts_by_event_type": {},
            "counts_by_day": [],
        }
    )

    from metronix.api.dependencies import get_agent_registry_service
    from metronix.api.routes.agents import get_activity_service

    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = _make_viewer
    app.dependency_overrides[get_agent_registry_service] = lambda: reg
    app.dependency_overrides[get_activity_service] = lambda: act
    return TestClient(app), reg, act


def test_activity_returns_404_for_unknown_agent() -> None:
    client, _, _ = _client(agent_exists=False)
    r = client.get("/api/v1/agents/unknown/activity")
    assert r.status_code == 404


def test_activity_returns_404_for_foreign_workspace_agent() -> None:
    """B1 defence-in-depth: agent exists but belongs to another workspace."""
    client, reg, _ = _client(agent_exists=True)
    # Override the registered agent so it claims a different workspace
    foreign_rec = MagicMock()
    foreign_rec.id = "ag_1"
    foreign_rec.workspace_id = "other_ws"
    reg.get_agent = AsyncMock(return_value=foreign_rec)
    r = client.get("/api/v1/agents/ag_1/activity")
    assert r.status_code == 404
    r = client.get("/api/v1/agents/ag_1/activity/summary")
    assert r.status_code == 404


def test_activity_shape_and_filters() -> None:
    rows = [
        {
            "id": 1,
            "workspace_id": "default",
            "agent_id": "ag_1",
            "session_id": "s1",
            "event_type": "memory.created",
            "event_data": {"record_id": "r1"},
            "created_at": datetime(2026, 4, 23, 10, 0, tzinfo=UTC),
        }
    ]
    client, _, act = _client(activity_rows=rows)
    r = client.get(
        "/api/v1/agents/ag_1/activity",
        params=[
            ("event_type", "memory.created"),
            ("session_id", "s1"),
            ("limit", 10),
        ],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["event_type"] == "memory.created"
    assert body["events"][0]["event_data"]["record_id"] == "r1"
    assert body["has_more"] is False
    # Filters propagated to the service
    kwargs = act.list_for_agent.await_args.kwargs
    assert kwargs["event_types"] == ["memory.created"]
    assert kwargs["session_id"] == "s1"
    assert kwargs["limit"] == 10


def test_activity_has_more_true() -> None:
    rows = [
        {
            "id": i,
            "workspace_id": "default",
            "agent_id": "ag_1",
            "session_id": None,
            "event_type": "memory.created",
            "event_data": {},
            "created_at": datetime(2026, 4, 23, tzinfo=UTC),
        }
        for i in range(5)
    ]
    client, _, _ = _client(activity_rows=rows, has_more=True)
    r = client.get("/api/v1/agents/ag_1/activity?limit=5")
    assert r.status_code == 200
    assert r.json()["has_more"] is True


def test_activity_summary_default_period() -> None:
    client, _, act = _client()
    r = client.get("/api/v1/agents/ag_1/activity/summary")
    assert r.status_code == 200
    assert act.summary_for_agent.await_args.kwargs["period"] == "7d"


def test_activity_summary_invalid_period_returns_400() -> None:
    from metronix.api.dependencies import get_agent_registry_service
    from metronix.api.routes.agents import get_activity_service

    app = create_app(Settings(AUTH_ENABLED=False))
    reg = MagicMock()
    reg.workspace_id = "default"
    rec = MagicMock()
    rec.id = "ag_1"
    rec.workspace_id = "default"
    reg.get_agent = AsyncMock(return_value=rec)

    act = MagicMock()
    act.summary_for_agent = AsyncMock(side_effect=ValueError("invalid period: 'bogus'"))

    app.dependency_overrides[get_current_user] = _make_viewer
    app.dependency_overrides[get_agent_registry_service] = lambda: reg
    app.dependency_overrides[get_activity_service] = lambda: act
    client = TestClient(app)
    r = client.get("/api/v1/agents/ag_1/activity/summary?period=bogus")
    assert r.status_code == 400
    assert "period" in r.json()["detail"]


def test_activity_summary_returns_404_for_unknown_agent() -> None:
    client, _, _ = _client(agent_exists=False)
    r = client.get("/api/v1/agents/unknown/activity/summary")
    assert r.status_code == 404
