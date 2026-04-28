"""Integration test for ``GET /api/v1/memory/records/{id}`` cross-workspace 404.

Requires PostgreSQL (migration 013 applied). Saves a record in workspace A
through ``MemoryPostgresStore``, then issues a request authenticated as a
user in workspace B and expects 404 — confirming workspace isolation
enforced at the PG layer (``WHERE workspace_id = :ws``).

Skipped unless ``RUN_INTEGRATION_TESTS=1`` (matches existing integration
test gating in this repo).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.api.app import create_app
from metatron.auth.dependencies import get_current_user
from metatron.core.config import Settings
from metatron.core.models import MemoryRecord, MemoryScope, Role, User
from metatron.storage.memory_postgres import MemoryPostgresStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="integration tests require RUN_INTEGRATION_TESTS=1",
    ),
]


def _make_user_in(workspace_id: str) -> User:
    return User(
        id="u-integration",
        username="integration",
        email="i@example.com",
        role=Role.EDITOR,
        workspace_ids=[workspace_id],
    )


async def test_get_record_cross_workspace_returns_404() -> None:
    """Record in workspace A; auth as workspace B ⇒ 404 (workspace isolation)."""
    settings = Settings(AUTH_ENABLED=False)
    workspace_a = f"ws-it-a-{uuid4().hex[:8]}"
    workspace_b = f"ws-it-b-{uuid4().hex[:8]}"
    record_id = uuid4().hex

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg = MemoryPostgresStore(engine)

    try:
        # Seed a record in workspace A.
        record = MemoryRecord(
            id=record_id,
            workspace_id=workspace_a,
            agent_id="agent-it",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="cross-workspace isolation",
        )
        await pg.save(record)

        app = create_app(settings)
        # Auth as a user in workspace B — they should not see workspace A's record.
        app.dependency_overrides[get_current_user] = lambda: _make_user_in(workspace_b)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/api/v1/memory/records/{record_id}")

        assert response.status_code == 404, response.text

        # Sanity: a user authenticated for workspace A *can* read it.
        app.dependency_overrides[get_current_user] = lambda: _make_user_in(workspace_a)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response_a = await client.get(f"/api/v1/memory/records/{record_id}")
        assert response_a.status_code == 200, response_a.text
        assert response_a.json()["id"] == record_id
    finally:
        # Cleanup PG.
        await pg.delete(workspace_a, record_id)
        await engine.dispose()
