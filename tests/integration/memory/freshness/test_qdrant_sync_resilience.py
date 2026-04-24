"""Integration test: worker tolerates Qdrant sync failures (MTRNIX-322).

Reproduces a Qdrant outage by monkey-patching
``MemoryQdrantStore.update_payload`` to raise. The worker iteration must:

1. Commit the PG lifecycle transition (Monitor → ARCHIVED).
2. Swallow the Qdrant error inside ``MemoryTarget.sync_downstream_stores``.
3. Increment the ``freshness_qdrant_sync_failed_total`` counter.
4. Return normally from ``run_once`` without raising.

After the outage "ends" (patch lifted), the backfill script — or a
subsequent `update_payload` — clears the drift. That recovery path is
exercised by the existing script, not this test; here we only pin the
no-abort behaviour under outage.

Requires: PostgreSQL, Qdrant, Redis (services assumed already up).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
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
from metatron.freshness import metrics as freshness_metrics
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


async def test_qdrant_outage_does_not_abort_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", True)

    workspace = f"fresh-322r-{uuid4().hex[:8]}"
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

    # Patch the Prometheus counter with a chain mock so we can assert it was
    # bumped. We can't read real counter values because ``prometheus_client``
    # is an optional dep and the runtime may be using the ``_NoopMetric``
    # stub. This patch works under both branches.
    mock_counter = MagicMock()
    mock_counter.labels.return_value = mock_counter
    monkeypatch.setattr(freshness_metrics, "qdrant_sync_failed", mock_counter)

    try:
        # --- Seed ---
        record = MemoryRecord(
            id=record_id,
            workspace_id=workspace,
            agent_id="agent-322r",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="Failover: Stripe webhook retries 3x with exponential backoff.",
            content_hash="322r-" + record_id[:12],
        )
        await pg_store.save(record)
        await pg_store.update_lifecycle(
            workspace,
            record_id,
            valid_until=datetime.now(UTC) - timedelta(days=1),
        )
        await qdrant.upsert(record)

        # --- Patch Qdrant update_payload to simulate outage ---
        async def _boom(self, *_args, **_kwargs):  # noqa: ANN001 — duck typing
            raise RuntimeError("qdrant down")

        monkeypatch.setattr(MemoryQdrantStore, "update_payload", _boom)

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

        await coordination.enqueue_job(
            FreshnessJob(
                workspace_id=workspace,
                event_type="knowledge_changed",
                target_kind="memory_record",
                target_id=record_id,
            )
        )

        # --- Run worker: MUST NOT RAISE despite Qdrant outage ---
        processed = await worker.run_once(max_jobs=5)
        assert processed == 1

        # --- PG: transition still committed ---
        fetched = await pg_store.get(workspace, record_id)
        assert fetched is not None
        assert fetched.status is LifecycleStatus.ARCHIVED

        # --- MachineEvents: Monitor completed event recorded ---
        events = await freshness_pg.list_events_for_target(workspace, "memory_record", record_id)
        stage_events = [e for e in events if e.event_type == "freshness_stage_completed"]
        monitor_events = [
            e
            for e in stage_events
            if (isinstance(e.payload, dict) and e.payload.get("stage") == "monitor")
        ]
        assert len(monitor_events) >= 1, (
            f"Monitor stage MachineEvent missing; events={[e.event_type for e in events]}"
        )

        # --- Counter: incremented at least once with the right labels ---
        assert mock_counter.labels.call_count >= 1
        # Every call must carry the expected labels.
        for call in mock_counter.labels.call_args_list:
            assert call.kwargs == {
                "target_kind": "memory_record",
                "stage": "sync_downstream",
            }
        assert mock_counter.inc.call_count >= 1
    finally:
        await _cleanup(engine, workspace)
        with contextlib.suppress(Exception):
            await qdrant.close()
        await redis.close()
        await engine.dispose()
