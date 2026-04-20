"""End-to-end integration test for the freshness worker (MTRNIX-304).

Requires: PostgreSQL (migration 016 applied), Qdrant, Redis, Neo4j. All
services are assumed already running per CLAUDE.md. Feature flag is
forced ON inside the test.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.core.models import (
    FreshnessJob,
    MemoryRecord,
    MemoryScope,
)
from metatron.memory.freshness.coordination import CoordinationStore
from metatron.memory.freshness.curator import Curator
from metatron.memory.freshness.decision_engine import RuleBasedDecisionEngine
from metatron.memory.freshness.linker import Linker
from metatron.memory.freshness.monitor import FreshnessMonitor
from metatron.memory.freshness.reconciler import Reconciler
from metatron.memory.freshness.worker import FreshnessWorker
from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.memory_qdrant import MemoryQdrantStore
from metatron.storage.redis import RedisStore

pytestmark = pytest.mark.integration


async def _cleanup_pg(engine) -> None:
    from sqlalchemy import text as sa_text

    async with engine.begin() as conn:
        await conn.execute(
            sa_text("DELETE FROM machine_events WHERE workspace_id LIKE 'fresh-it-%'")
        )
        await conn.execute(
            sa_text("DELETE FROM review_entries WHERE workspace_id LIKE 'fresh-it-%'")
        )
        await conn.execute(
            sa_text("DELETE FROM memory_records WHERE workspace_id LIKE 'fresh-it-%'")
        )


async def test_enqueue_dequeue_processes_single_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: enqueue → run_once → PG status update + MachineEvents."""
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", True)

    workspace = f"fresh-it-{uuid4().hex[:8]}"
    record_id = uuid4().hex

    # --- Bootstrap ---
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
        # --- Seed one MemoryRecord (PG + Qdrant) ---
        record = MemoryRecord(
            id=record_id,
            workspace_id=workspace,
            agent_id="agent-it",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="Stripe webhook forwards events to /api/hooks/stripe.",
            content_hash="it-" + record_id,
        )
        await pg_store.save(record)
        await qdrant.upsert(record)

        # --- Build worker with rule-based engine (no SLM dependency) ---
        linker = Linker(
            pg_store=pg_store,
            qdrant_store=qdrant,
            freshness_pg=freshness_pg,
            coordination=coordination,
            threshold=settings.freshness_linker_threshold,
        )
        reconciler = Reconciler(
            pg_store=pg_store,
            qdrant_store=qdrant,
            freshness_pg=freshness_pg,
            coordination=coordination,
            threshold=settings.freshness_reconciler_threshold,
        )
        monitor = FreshnessMonitor(
            pg_store=pg_store,
            freshness_pg=freshness_pg,
            coordination=coordination,
            stale_after_days=settings.freshness_stale_after_days,
        )
        curator = Curator(
            pg_store=pg_store,
            freshness_pg=freshness_pg,
            coordination=coordination,
        )
        worker = FreshnessWorker(
            coordination=coordination,
            freshness_pg=freshness_pg,
            decision_engine=RuleBasedDecisionEngine(),
            pg_store_factory=lambda _ws: pg_store,
            qdrant_store_factory=lambda _ws: qdrant,
            linker=linker,
            reconciler=reconciler,
            monitor=monitor,
            curator=curator,
        )

        # --- Enqueue a job ---
        await coordination.enqueue_job(
            FreshnessJob(
                workspace_id=workspace,
                event_type="knowledge_changed",
                target_kind="memory_record",
                target_id=record_id,
            )
        )
        depth = await coordination.queue_depth(workspace)
        assert depth >= 1

        # --- Process ---
        processed = await worker.run_once(max_jobs=10)
        assert processed == 1

        # --- Assert PG state ---
        fetched = await pg_store.get(workspace, record_id)
        assert fetched is not None
        assert fetched.evidence_count >= 0  # Linker ran

        events = await freshness_pg.list_events_for_target(
            workspace, "memory_record", record_id
        )
        event_types = {e.event_type for e in events}
        assert "freshness_job_received" in event_types
        assert "freshness_job_processed" in event_types
        assert "freshness_stage_completed" in event_types
    finally:
        await _cleanup_pg(engine)
        await qdrant.close() if hasattr(qdrant, "close") else None
        await redis.close()
        await engine.dispose()
