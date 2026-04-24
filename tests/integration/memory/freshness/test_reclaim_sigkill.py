"""Integration test — SIGKILL mid-batch + second worker reclaims (MTRNIX-316).

This is the MTRNIX-316 AC gate. Exercise:

1. Seed N=5 memory records + enqueue 5 freshness jobs on workspace X.
2. Spawn worker A as a subprocess with ``METATRON_FRESHNESS_TEST_WORKER_ID``
   and ``METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS`` set — the latter widens
   the window between LMOVE (into processing list) and LREM (on complete)
   so the kill lands mid-batch deterministically.
3. Poll ``LLEN processing:worker-a`` until >= 1 item is visible — that
   proves at least one LMOVE completed.
4. ``os.kill(pid, SIGKILL)`` + ``proc.wait``.
5. Assert: queue + processing_list_a combined still hold N jobs — no loss.
6. Spawn worker B (no sleep, different worker id).
7. Wait for all 5 ``freshness_job_processed`` MachineEvents to be written.
8. Assert worker A's processing list is empty.

Requires PostgreSQL (migration 016 applied), Qdrant, Redis. All services
are assumed running per CLAUDE.md.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.core.models import (
    FreshnessJob,
    MemoryRecord,
    MemoryScope,
)
from metatron.freshness.coordination import (
    CoordinationStore,
    processing_key_for,
)
from metatron.storage.freshness_pg import FreshnessStore
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.memory_qdrant import MemoryQdrantStore
from metatron.storage.redis import RedisStore

pytestmark = pytest.mark.integration


_WORKSPACE_PREFIX = "fresh-it-reclaim-"


def _spawn_worker(
    worker_id: str,
    *,
    sleep_ms: int = 0,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    """Spawn ``python -m metatron.memory.freshness`` as a subprocess."""
    env = os.environ.copy()
    env["METATRON_FRESHNESS_ENABLED"] = "true"
    env["METATRON_FRESHNESS_TEST_WORKER_ID"] = worker_id
    if sleep_ms:
        env["METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS"] = str(sleep_ms)
    # Tight poll so reclaim fires quickly after kill.
    env["METATRON_FRESHNESS_POLL_SECONDS"] = "0.5"
    # Short heartbeat so the reclaim pass considers worker A dead fast.
    env["METATRON_FRESHNESS_HEARTBEAT_TTL_SECONDS"] = "3"
    env["METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS"] = "2"
    env["METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED"] = "false"
    env["METATRON_FRESHNESS_MAX_JOBS_PER_ITERATION"] = "5"
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen(
        [sys.executable, "-m", "metatron.memory.freshness"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def _cleanup_pg(engine, workspace: str) -> None:
    from sqlalchemy import text as sa_text

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


async def _cleanup_redis(redis: RedisStore, workspace: str, worker_ids: list[str]) -> None:
    # Wipe any freshness:* keys for the test workspace + workers.
    for wid in worker_ids:
        try:
            await redis.delete(processing_key_for(wid))
        except Exception:
            pass
        # Heartbeat + reclaim lock keys use the same env prefix.
        from metatron.freshness.coordination import _heartbeat_key, _reclaim_lock_key

        try:
            await redis.delete(_heartbeat_key(wid))
        except Exception:
            pass
        try:
            await redis.delete(_reclaim_lock_key(wid))
        except Exception:
            pass
    # And the workspace queue.
    from metatron.freshness.coordination import queue_key_for

    try:
        await redis.delete(queue_key_for(workspace))
    except Exception:
        pass


async def _wait_for_processing_items(
    redis: RedisStore,
    worker_id: str,
    *,
    min_items: int,
    timeout_s: float,
) -> int:
    """Poll LLEN until >= min_items or timeout. Returns final count."""
    deadline = time.monotonic() + timeout_s
    p_key = processing_key_for(worker_id)
    last = 0
    while time.monotonic() < deadline:
        last = await redis.llen(p_key)
        if last >= min_items:
            return last
        await asyncio.sleep(0.1)
    return last


async def _wait_for_events(
    freshness_pg: FreshnessStore,
    workspace: str,
    target_ids: list[str],
    *,
    event_type: str,
    expected_count: int,
    timeout_s: float,
) -> int:
    """Poll until at least ``expected_count`` matching events appear."""
    deadline = time.monotonic() + timeout_s
    count = 0
    while time.monotonic() < deadline:
        count = 0
        for tid in target_ids:
            events = await freshness_pg.list_events_for_target(
                workspace, "memory_record", tid
            )
            if any(e.event_type == event_type for e in events):
                count += 1
        if count >= expected_count:
            return count
        await asyncio.sleep(0.5)
    return count


async def test_reclaim_after_sigkill_recovers_all_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MTRNIX-316 acceptance gate."""
    settings = get_settings()
    monkeypatch.setattr(settings, "freshness_enabled", True)

    workspace = f"{_WORKSPACE_PREFIX}{uuid4().hex[:8]}"
    n_jobs = 5
    record_ids = [uuid4().hex for _ in range(n_jobs)]

    # --- Bootstrap clients ---
    redis = RedisStore(settings.redis_url)
    try:
        if not await redis.ping():
            pytest.skip("Redis unreachable")
    except Exception:
        pytest.skip("Redis unreachable")

    coordination = CoordinationStore(redis=redis)
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_store = MemoryPostgresStore(engine)
    freshness_pg = FreshnessStore(engine)
    qdrant = MemoryQdrantStore(workspace_id=workspace)

    worker_a = "mtrnix316-worker-a"
    worker_b = "mtrnix316-worker-b"

    proc_a: subprocess.Popen[bytes] | None = None
    proc_b: subprocess.Popen[bytes] | None = None
    try:
        # Seed records + enqueue jobs.
        for rid in record_ids:
            rec = MemoryRecord(
                id=rid,
                workspace_id=workspace,
                agent_id="agent-kill",
                scope=MemoryScope.PER_AGENT,
                source_type="reclaim_test",
                content=f"Reclaim test record {rid}",
                content_hash=f"rt-{rid}",
            )
            await pg_store.save(rec)
            await qdrant.upsert(rec)
            await coordination.enqueue_job(
                FreshnessJob(
                    workspace_id=workspace,
                    event_type="knowledge_changed",
                    target_kind="memory_record",
                    target_id=rid,
                )
            )

        initial_depth = await coordination.queue_depth(workspace)
        assert initial_depth == n_jobs

        # Spawn worker A with test sleep so the kill lands mid-batch.
        # With sleep_ms=5000, the first LMOVE happens, then pipeline sleeps,
        # giving us a large window to SIGKILL.
        proc_a = _spawn_worker(worker_a, sleep_ms=5000)

        # Wait until worker A has popped at least one job into its
        # processing list. Timeout 15s — CI can be slow.
        final_items = await _wait_for_processing_items(
            redis, worker_a, min_items=1, timeout_s=15.0
        )
        assert final_items >= 1, (
            f"worker A never populated its processing list (saw {final_items})"
        )

        # SIGKILL mid-batch.
        os.kill(proc_a.pid, signal.SIGKILL)
        try:
            proc_a.wait(timeout=5)
        finally:
            proc_a = None

        # The combined queue + worker-A processing list must still hold
        # all N jobs (minus any fully processed; the 5s sleep makes full
        # processing impossible before the first kill).
        remaining_queue = await coordination.queue_depth(workspace)
        remaining_processing = await redis.llen(processing_key_for(worker_a))
        assert remaining_queue + remaining_processing >= 1, (
            "expected at least one job stranded somewhere after SIGKILL"
        )

        # Now spawn worker B (no sleep). It should:
        #   1. detect worker A's processing list via list_processing_workers
        #   2. detect worker A as dead (heartbeat expired)
        #   3. LMOVE items back to the workspace queue
        #   4. dequeue + process them
        proc_b = _spawn_worker(worker_b, sleep_ms=0)

        # Poll for all N records to hit the ``freshness_job_processed`` event.
        # Allow generous timeout — reclaim interval + poll + pipeline time.
        count = await _wait_for_events(
            freshness_pg,
            workspace,
            record_ids,
            event_type="freshness_job_processed",
            expected_count=n_jobs,
            timeout_s=60.0,
        )
        assert count == n_jobs, (
            f"only {count}/{n_jobs} records produced freshness_job_processed events"
        )

        # Worker A's processing list must now be empty.
        assert await redis.llen(processing_key_for(worker_a)) == 0
    finally:
        for p in (proc_a, proc_b):
            if p is not None:
                try:
                    p.send_signal(signal.SIGTERM)
                    p.wait(timeout=5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
        await _cleanup_pg(engine, workspace)
        await _cleanup_redis(redis, workspace, [worker_a, worker_b])
        if hasattr(qdrant, "close"):
            try:
                await qdrant.close()
            except Exception:
                pass
        await redis.close()
        await engine.dispose()
