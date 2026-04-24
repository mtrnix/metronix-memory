"""Integration test — scheduled scan rescues stale records (MTRNIX-316).

Seeds memory records with ``updated_at`` past the stale threshold + one
control record inside the window. Calls ``ScheduledScan.run()`` once and
asserts only the stale records get enqueued.

Requires PostgreSQL (migration 016 applied), Qdrant, Redis live.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.core.models import MemoryRecord, MemoryScope
from metatron.freshness.coordination import (
    CoordinationStore,
    queue_key_for,
)
from metatron.freshness.scheduled_scan import ScheduledScan
from metatron.memory.freshness.target_memory import MemoryTarget
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.redis import RedisStore

pytestmark = pytest.mark.integration


_WORKSPACE_PREFIX = "fresh-it-scan-"


async def _cleanup_pg(engine, workspace: str) -> None:
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


async def _force_updated_at(engine, record_id: str, updated_at: datetime) -> None:
    """Override ``updated_at`` — bypasses the ``save()`` path's default-now behaviour."""
    async with engine.begin() as conn:
        await conn.execute(
            sa_text("UPDATE memory_records SET updated_at = :updated WHERE id = :id"),
            {"updated": updated_at, "id": record_id},
        )


async def test_scheduled_scan_enqueues_only_stale_records() -> None:
    settings = get_settings()
    workspace = f"{_WORKSPACE_PREFIX}{uuid4().hex[:8]}"

    redis = RedisStore(settings.redis_url)
    try:
        if not await redis.ping():
            pytest.skip("Redis unreachable")
    except Exception:
        pytest.skip("Redis unreachable")

    coordination = CoordinationStore(redis=redis)
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_store = MemoryPostgresStore(engine)

    # Seed 3 stale records + 1 control.
    stale_ids = [uuid4().hex for _ in range(3)]
    control_id = uuid4().hex
    stale_updated_at = datetime.now(UTC) - timedelta(days=40)

    try:
        # Clear out any residual keys.
        await redis.delete(queue_key_for(workspace))

        # Fake qdrant factory — scheduled-scan path does not embed/upsert.
        class _FakeQdrant:
            async def search(self, *_args: object, **_kwargs: object) -> list[object]:
                return []

            async def update_payload(self, *_args: object, **_kwargs: object) -> None:
                return None

        memory_target = MemoryTarget(
            pg_store=pg_store,
            qdrant_store_factory=lambda _ws: _FakeQdrant(),  # type: ignore[arg-type, return-value]
        )

        for rid in stale_ids:
            rec = MemoryRecord(
                id=rid,
                workspace_id=workspace,
                agent_id="agent-scan",
                scope=MemoryScope.PER_AGENT,
                source_type="scan_test",
                content=f"Stale record {rid}",
                content_hash=f"scan-{rid}",
            )
            await pg_store.save(rec)
            await _force_updated_at(engine, rid, stale_updated_at)

        rec_control = MemoryRecord(
            id=control_id,
            workspace_id=workspace,
            agent_id="agent-scan",
            scope=MemoryScope.PER_AGENT,
            source_type="scan_test",
            content="Fresh control record",
            content_hash=f"scan-{control_id}",
        )
        await pg_store.save(rec_control)

        async def lister() -> list[str]:
            return [workspace]

        scan = ScheduledScan(
            target_kind="memory_record",
            target=memory_target,
            coordination=coordination,
            workspace_lister=lister,
            stale_after_days=30,  # stale_updated_at is 40 days old → 3 candidates
            batch_limit=100,
        )

        enqueued = await scan.run()

        # Exactly 3 stale records enqueued, control untouched.
        assert enqueued == 3
        depth = await coordination.queue_depth(workspace)
        assert depth == 3

        # Drain the queue and verify each payload references a stale id
        # (worker_id is a kwarg; the scheduled_scan integration does not
        # need the LMOVE into a processing list — we just inspect payloads
        # via a direct redis call).
        jobs = await coordination.dequeue_batch(workspace, max_items=10, worker_id="test-scan-w")
        assert len(jobs) == 3
        seen_ids = {j.target_id for j in jobs}
        assert seen_ids == set(stale_ids)
        assert control_id not in seen_ids
        for job in jobs:
            assert job.event_type == "scheduled_scan"
            assert job.target_kind == "memory_record"
            assert "older_than_iso" in job.payload
    finally:
        await _cleanup_pg(engine, workspace)
        try:
            await redis.delete(queue_key_for(workspace))
        except Exception:
            pass
        # Also drop any residual processing list for the test worker id.
        from metatron.freshness.coordination import processing_key_for

        try:
            await redis.delete(processing_key_for("test-scan-w"))
        except Exception:
            pass
        await redis.close()
        await engine.dispose()
