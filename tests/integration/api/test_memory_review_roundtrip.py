"""Integration test for ``/api/v1/memory/review`` GET + POST roundtrip.

Requires PostgreSQL (migrations 013 + 016 applied — ``memory_records``,
``review_entries``, ``machine_events``). Saves a memory record + a pending
review entry directly via the storage layer, exercises the full REST
surface (list → resolve), then verifies the side-effects: review row
deleted, lifecycle status flipped, MachineEvent appended with the user's id
as the actor.

Skipped unless ``RUN_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.api.app import create_app
from metronix.auth.dependencies import get_current_user
from metronix.core.config import Settings
from metronix.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    ReviewEntry,
    Role,
    User,
)
from metronix.storage.freshness_pg import FreshnessStore
from metronix.storage.memory_postgres import MemoryPostgresStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="integration tests require RUN_INTEGRATION_TESTS=1",
    ),
]

_USER_ID = "u-integration"


def _make_user(workspace_id: str) -> User:
    return User(
        id=_USER_ID,
        username="integration",
        email="i@example.com",
        role=Role.EDITOR,
        workspace_ids=[workspace_id],
    )


async def test_review_roundtrip_get_then_resolve_keep() -> None:
    """List then resolve(keep): review deleted, status=ACTIVE, MachineEvent emitted."""
    settings = Settings(AUTH_ENABLED=False)
    workspace_id = f"ws-it-rev-{uuid4().hex[:8]}"
    record_id = uuid4().hex
    review_id = uuid4().hex

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg = MemoryPostgresStore(engine)
    freshness = FreshnessStore(engine)

    try:
        # --- Seed a memory record + a review entry referencing it ---
        record = MemoryRecord(
            id=record_id,
            workspace_id=workspace_id,
            agent_id="agent-it",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="review queue roundtrip seed",
            status=LifecycleStatus.REVIEW_NEEDED,
        )
        await pg.save(record)

        entry = ReviewEntry(
            id=review_id,
            workspace_id=workspace_id,
            target_id=record_id,
            target_kind="memory_record",
            reason="possible_duplicate",
            related_record_id=None,
            content="possible duplicate detected",
            confidence=0.8,
        )
        await freshness.save_review_entry(entry)

        app = create_app(settings)
        app.dependency_overrides[get_current_user] = lambda: _make_user(workspace_id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # --- GET /review — review entry visible ---
            r = await client.get("/api/v1/memory/review")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] == 1
            assert body["count"] == 1
            assert body["entries"][0]["id"] == review_id
            assert body["entries"][0]["target_id"] == record_id
            assert body["entries"][0]["reason"] == "possible_duplicate"

            # --- POST /review/{id} action=keep ---
            r = await client.post(
                f"/api/v1/memory/review/{review_id}",
                json={"action": "keep"},
            )
            assert r.status_code == 204, r.text

            # --- Re-GET — total drops to 0 ---
            r = await client.get("/api/v1/memory/review")
            assert r.status_code == 200, r.text
            assert r.json()["total"] == 0

        # --- Verify side-effects on PG ---
        # 1. Memory record status flipped to ACTIVE.
        refreshed = await pg.get(workspace_id, record_id)
        assert refreshed is not None
        assert refreshed.status == LifecycleStatus.ACTIVE

        # 2. MachineEvent row exists with the right shape.
        events = await freshness.list_events_for_target(workspace_id, "memory_record", record_id)
        resolved_events = [e for e in events if e.event_type == "freshness_review_resolved"]
        assert len(resolved_events) >= 1
        latest = resolved_events[0]
        assert latest.actor == _USER_ID
        assert latest.workspace_id == workspace_id
        assert latest.target_id == record_id
    finally:
        # Cleanup PG state in dependency order: events → review → record.
        from sqlalchemy import text as sa_text

        async with engine.begin() as conn:
            await conn.execute(
                sa_text("DELETE FROM machine_events WHERE workspace_id = :ws"),
                {"ws": workspace_id},
            )
            await conn.execute(
                sa_text("DELETE FROM review_entries WHERE workspace_id = :ws"),
                {"ws": workspace_id},
            )
        await pg.delete(workspace_id, record_id)
        await engine.dispose()
