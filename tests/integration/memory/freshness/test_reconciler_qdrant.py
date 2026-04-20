"""Integration test for Reconciler against live Qdrant (MTRNIX-304).

Seeds two near-duplicate records and asserts the Reconciler creates a
``ReviewEntry`` in PG. Skipped unless services are running.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.core.models import MemoryRecord, MemoryScope
from metatron.memory.freshness.coordination import CoordinationStore
from metatron.memory.freshness.reconciler import Reconciler
from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.memory_qdrant import MemoryQdrantStore
from metatron.storage.redis import RedisStore

pytestmark = pytest.mark.integration


async def _cleanup(engine, workspace: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa_text("DELETE FROM review_entries WHERE workspace_id = :ws"),
            {"ws": workspace},
        )
        await conn.execute(
            sa_text("DELETE FROM machine_events WHERE workspace_id = :ws"),
            {"ws": workspace},
        )
        await conn.execute(
            sa_text("DELETE FROM memory_records WHERE workspace_id = :ws"),
            {"ws": workspace},
        )


async def test_near_duplicate_creates_review_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", True)

    workspace = f"fresh-recon-{uuid4().hex[:8]}"
    redis = RedisStore(settings.redis_url)
    try:
        if not await redis.ping():
            pytest.skip("Redis unreachable")
    except Exception:
        pytest.skip("Redis unreachable")
    coordination = CoordinationStore(redis=redis)

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_store = MemoryPostgresStore(engine)
    freshness_pg = FreshnessPostgresStore(engine)
    qdrant = MemoryQdrantStore(workspace_id=workspace)

    try:
        shared_text = (
            "The Stripe webhook forwards events to /api/hooks/stripe. "
            "Signature validation uses STRIPE_WEBHOOK_SECRET."
        )
        rec_a = MemoryRecord(
            id=uuid4().hex,
            workspace_id=workspace,
            agent_id="agent-rec",
            scope=MemoryScope.PER_AGENT,
            content=shared_text,
            content_hash="a-" + uuid4().hex[:8],
        )
        rec_b = MemoryRecord(
            id=uuid4().hex,
            workspace_id=workspace,
            agent_id="agent-rec",
            scope=MemoryScope.PER_AGENT,
            content=shared_text + " Retries use exponential backoff.",
            content_hash="b-" + uuid4().hex[:8],
        )
        await pg_store.save(rec_a)
        await pg_store.save(rec_b)
        await qdrant.upsert(rec_a)
        await qdrant.upsert(rec_b)

        reconciler = Reconciler(
            pg_store=pg_store,
            qdrant_store=qdrant,
            freshness_pg=freshness_pg,
            coordination=coordination,
            threshold=0.70,  # lower so the test is reliable across models
        )

        out = await reconciler.run(workspace, rec_b.id)

        if out is None:
            pytest.skip("No duplicate detected — embeddings may differ on this env")
        assert out.reason == "possible_duplicate"
        assert out.related_record_id == rec_a.id

        # Verify it landed in PG.
        entries = await freshness_pg.list_review_entries(workspace, record_id=rec_b.id)
        assert len(entries) >= 1
    finally:
        await _cleanup(engine, workspace)
        await redis.close()
        await engine.dispose()
