"""Integration test for ``GET /api/v1/memory/graph`` Neo4j-down path.

Requires PostgreSQL (migration 013 applied). Spins up the FastAPI app via
``create_app(settings)`` against the live PG. Configures Neo4j to point at
a deliberately closed port so the storage helper raises a connection error,
exercising the service-layer fallback path (``records=[seed], edges=[]``).

The route must respond 200 with a single seed node and an empty edge list
when Neo4j is unavailable — graceful degradation per MTRNIX-324 spec.

Skipped unless ``RUN_INTEGRATION_TESTS=1``.
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


def _make_user(workspace_id: str) -> User:
    return User(
        id="u-integration",
        username="integration",
        email="i@example.com",
        role=Role.EDITOR,
        workspace_ids=[workspace_id],
    )


async def test_memory_graph_returns_seed_only_when_neo4j_down() -> None:
    """Neo4j down ⇒ 200 with nodes=[seed], edges=[] (graceful degradation)."""
    # Point Neo4j at a closed local port — `connect()` will raise
    # ServiceUnavailable / ConnectionError, which the service catches.
    settings = Settings(
        AUTH_ENABLED=False,
        NEO4J_URI="bolt://127.0.0.1:1",  # closed port → connection refused
        NEO4J_USER="x",
        NEO4J_PASSWORD="x",
    )
    workspace_id = f"ws-it-graph-{uuid4().hex[:8]}"
    record_id = uuid4().hex

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg = MemoryPostgresStore(engine)

    try:
        # Seed one record in PG so the service can hydrate the seed.
        record = MemoryRecord(
            id=record_id,
            workspace_id=workspace_id,
            agent_id="agent-it",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="graph fallback seed",
        )
        await pg.save(record)

        app = create_app(settings)
        app.dependency_overrides[get_current_user] = lambda: _make_user(workspace_id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/memory/graph",
                params={"seed_record_id": record_id, "depth": 1},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        # Seed is the only node; no edges because Neo4j is unreachable.
        assert len(body["nodes"]) == 1
        assert body["nodes"][0]["id"] == record_id
        assert body["edges"] == []
    finally:
        await pg.delete(workspace_id, record_id)
        await engine.dispose()
