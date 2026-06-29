"""End-to-end smoke: memory_store → agent_activity_log → REST list/summary.

Requires a live PostgreSQL (port 5433 via docker-compose). Skipped unless
``RUN_INTEGRATION_TESTS=1`` is set.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="integration tests require RUN_INTEGRATION_TESTS=1",
)


def _make_editor():  # type: ignore[no-untyped-def]
    """Bypass HTTPBearer auth for integration tests via dependency override.

    `require_editor` and `require_viewer` are FastAPI deps that read
    `request.state.user` set by `get_current_user`. Overriding the latter
    short-circuits the bearer-token check so we can hit endpoints without
    minting a JWT.
    """
    from metronix.core.models import Role, User  # type: ignore[import-untyped]

    return User(
        id="u_integration",
        username="integration",
        email="i@example.com",
        role=Role.EDITOR,
        workspace_ids=["default"],
    )


async def test_memory_cycle_produces_activity_rows() -> None:
    """Create agent → store memory → verify activity rows → read timeline + summary."""
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from metronix.api.app import create_app  # type: ignore[import-untyped]
    from metronix.auth.dependencies import get_current_user  # type: ignore[import-untyped]
    from metronix.core.config import Settings  # type: ignore[import-untyped]

    settings = Settings(METRONIX_ACTIVITY_LOG_ENABLED=True, AUTH_ENABLED=False)
    app = create_app(settings)
    app.dependency_overrides[get_current_user] = _make_editor

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Create an agent
        r = await client.post(
            "/api/v1/agents",
            json={"name": f"smoke-{int(time.time())}", "model": "test"},
        )
        assert r.status_code == 201, r.text
        agent_id = r.json()["id"]

        # 2. Store a memory record for that agent (REST with X-Agent-Id propagation)
        r = await client.post(
            "/api/v1/memory/records",
            json={
                "agent_id": agent_id,
                "content": "hello world",
                "scope": "per_agent",
                "source_type": "conversation",
            },
            headers={"X-Agent-Id": agent_id},
        )
        assert r.status_code in (200, 201), r.text

        # 3. Poll activity — emission is synchronous on the request path, retry for CI
        body: dict[str, Any] = {"count": 0}
        for _ in range(3):
            r = await client.get(f"/api/v1/agents/{agent_id}/activity?event_type=memory.created")
            body = r.json() if r.status_code == 200 else {"count": 0}
            if r.status_code == 200 and body.get("count", 0) >= 1:
                break
            await asyncio.sleep(0.2)
        assert r.status_code == 200
        assert body["count"] >= 1
        assert body["events"][0]["event_type"] == "memory.created"
        assert body["events"][0]["agent_id"] == agent_id

        # 4. Summary reports a non-zero count
        r = await client.get(f"/api/v1/agents/{agent_id}/activity/summary?period=1d")
        assert r.status_code == 200
        s = r.json()
        assert s["total_events"] >= 1
        assert s["counts_by_event_type"].get("memory.created", 0) >= 1
        assert isinstance(s["counts_by_day"], list)
        # A 1d window may span 1 or 2 calendar days depending on time-of-day.
        assert 1 <= len(s["counts_by_day"]) <= 2

        # 5. Activity log is gated by agent scope — 404 for unknown agent
        r = await client.get("/api/v1/agents/does-not-exist/activity")
        assert r.status_code == 404


async def test_overhead_budget_placeholder() -> None:
    """Placeholder — overhead measurement requires stable harness.

    Spec sets the budget at ≤25 ms for the memory_store cycle with logger on
    vs. off. Implement with a warm-up request + two measured cycles once the
    harness is stabilised. For now, skip to record the intention.
    """
    pytest.skip("Overhead harness deferred — see T16 plan notes.")
