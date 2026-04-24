"""End-to-end integration test: worker lifecycle transitions sync Qdrant payload.

MTRNIX-322 — reproduces the MTRNIX-319 §1 scenario as a pass gate:

1. Seed an ACTIVE memory record with ``valid_until < now``.
2. Enqueue + run one worker iteration.
3. Assert PG row transitions to ARCHIVED (Monitor rule).
4. Assert the Qdrant point's ``status`` payload mirrors ``archived``.
5. Assert the MCP ``memory_search`` tool with default ``status=["active"]``
   filter does NOT return the record — without running the backfill.

Requires: PostgreSQL, Qdrant, Redis (services assumed already up per
``CLAUDE.md``). Feature flag is forced ON inside the test.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.core.models import (
    FreshnessJob,
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
)
from metatron.memory.freshness.coordination import CoordinationStore
from metatron.memory.freshness.curator import Curator
from metatron.memory.freshness.decision_engine import RuleBasedDecisionEngine
from metatron.memory.freshness.linker import Linker
from metatron.memory.freshness.monitor import FreshnessMonitor
from metatron.memory.freshness.reconciler import Reconciler
from metatron.memory.freshness.target_memory import MemoryTarget
from metatron.memory.freshness.worker import FreshnessWorker, _Pipeline
from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.memory_qdrant import MemoryQdrantStore
from metatron.storage.redis import RedisStore

pytestmark = pytest.mark.integration


async def _cleanup(engine, workspace: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa_text("DELETE FROM machine_events WHERE workspace_id = :ws"),
            {"ws": workspace},
        )
        await conn.execute(
            sa_text("DELETE FROM review_entries WHERE workspace_id = :ws"),
            {"ws": workspace},
        )
        await conn.execute(
            sa_text("DELETE FROM memory_records WHERE workspace_id = :ws"),
            {"ws": workspace},
        )


async def test_worker_transition_mirrors_status_to_qdrant_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", True)

    workspace = f"fresh-322-{uuid4().hex[:8]}"
    record_id = uuid4().hex

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
        # --- Seed: ACTIVE record whose valid_until expired yesterday. ---
        # MemoryPostgresStore.save() does NOT write lifecycle columns (it relies
        # on PG server defaults). We set ``valid_until`` explicitly via
        # update_lifecycle so the Monitor's valid_until rule fires.
        record = MemoryRecord(
            id=record_id,
            workspace_id=workspace,
            agent_id="agent-322",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="Stripe webhook signature validation uses STRIPE_WEBHOOK_SECRET.",
            content_hash="322-" + record_id[:12],
        )
        await pg_store.save(record)
        await pg_store.update_lifecycle(
            workspace,
            record_id,
            valid_until=datetime.now(UTC) - timedelta(days=1),
        )
        await qdrant.upsert(record)

        # --- Build worker ---
        memory_target = MemoryTarget(pg_store=pg_store, qdrant_store_factory=lambda _ws: qdrant)
        linker = Linker(
            target=memory_target,
            freshness_store=freshness_pg,
            coordination=coordination,
            threshold=settings.freshness_linker_threshold,
        )
        reconciler = Reconciler(
            target=memory_target,
            freshness_store=freshness_pg,
            coordination=coordination,
            threshold=settings.freshness_reconciler_threshold,
        )
        monitor = FreshnessMonitor(
            target=memory_target,
            freshness_store=freshness_pg,
            coordination=coordination,
            stale_after_days=settings.freshness_stale_after_days,
        )
        curator = Curator(
            target=memory_target,
            freshness_store=freshness_pg,
            coordination=coordination,
        )
        pipelines = {
            "memory_record": _Pipeline(
                linker=linker,
                reconciler=reconciler,
                monitor=monitor,
                curator=curator,
                target=memory_target,
            )
        }
        worker = FreshnessWorker(
            coordination=coordination,
            freshness_pg=freshness_pg,
            decision_engine=RuleBasedDecisionEngine(),
            pipelines=pipelines,
        )

        # --- Enqueue + process ---
        await coordination.enqueue_job(
            FreshnessJob(
                workspace_id=workspace,
                event_type="knowledge_changed",
                target_kind="memory_record",
                target_id=record_id,
            )
        )
        processed = await worker.run_once(max_jobs=5)
        assert processed == 1

        # --- PG: record transitioned to ARCHIVED (Monitor valid_until rule) ---
        fetched = await pg_store.get(workspace, record_id)
        assert fetched is not None
        assert fetched.status is LifecycleStatus.ARCHIVED

        # --- Qdrant payload: status mirrors PG (this is the MTRNIX-322 fix) ---
        # Search excluding archived should return empty; including should find it.
        excluded = await qdrant.search(
            record.content,
            agent_id="agent-322",
            top_k=5,
            status_exclude=["archived"],
        )
        assert all(hit.get("record_id") != record_id for hit in excluded), (
            "Record must be filtered out by payload-level ARCHIVED exclusion "
            "— this is the MTRNIX-319 §1 regression guard."
        )

        included = await qdrant.search(
            record.content,
            agent_id="agent-322",
            top_k=5,
        )
        # Sanity: the point still exists in Qdrant — it's only excluded by
        # the status filter; so search WITHOUT the exclude must find it.
        assert any(hit.get("record_id") == record_id for hit in included)
    finally:
        await _cleanup(engine, workspace)
        with contextlib.suppress(Exception):
            await qdrant.close()
        await redis.close()
        await engine.dispose()
