"""Integration test — env-prefixed keys isolate dev rigs (MTRNIX-316).

Enqueue a freshness job while ``METRONIX_ENV=staging`` is in effect. Spawn a
worker under ``METRONIX_ENV=development`` and prove it never touches the
staging key. Then spawn a second worker under ``METRONIX_ENV=staging`` and
assert the job gets processed.

Requires PostgreSQL (migration 016 applied), Qdrant, Redis live.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core import config as config_mod
from metronix.core.config import get_settings
from metronix.core.models import FreshnessJob, MemoryRecord, MemoryScope
from metronix.freshness.coordination import CoordinationStore
from metronix.storage.freshness_pg import FreshnessStore
from metronix.storage.memory_postgres import MemoryPostgresStore
from metronix.storage.memory_qdrant import MemoryQdrantStore
from metronix.storage.redis import RedisStore

pytestmark = pytest.mark.integration


_WORKSPACE_PREFIX = "fresh-it-env-"


def _spawn_worker(env_override: str, worker_id: str) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["METRONIX_ENV"] = env_override
    env["METRONIX_FRESHNESS_ENABLED"] = "true"
    env["METRONIX_FRESHNESS_TEST_WORKER_ID"] = worker_id
    env["METRONIX_FRESHNESS_POLL_SECONDS"] = "0.5"
    env["METRONIX_FRESHNESS_HEARTBEAT_TTL_SECONDS"] = "3"
    env["METRONIX_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS"] = "3"
    env["METRONIX_FRESHNESS_SCHEDULED_SCAN_ENABLED"] = "false"
    env["METRONIX_FRESHNESS_MAX_JOBS_PER_ITERATION"] = "5"
    return subprocess.Popen(
        [sys.executable, "-m", "metronix.memory.freshness"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


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


async def _wait_for_event(
    freshness_pg: FreshnessStore,
    workspace: str,
    target_id: str,
    *,
    event_type: str,
    timeout_s: float,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        events = await freshness_pg.list_events_for_target(workspace, "memory_record", target_id)
        if any(e.event_type == event_type for e in events):
            return True
        await asyncio.sleep(0.5)
    return False


async def test_env_prefixed_keys_isolate_environments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()

    workspace = f"{_WORKSPACE_PREFIX}{uuid4().hex[:8]}"
    record_id = uuid4().hex

    redis = RedisStore(settings.redis_url)
    try:
        if not await redis.ping():
            pytest.skip("Redis unreachable")
    except Exception:
        pytest.skip("Redis unreachable")

    # Force ENV=staging in this process so enqueue uses staging-prefixed key.
    monkeypatch.setenv("METRONIX_ENV", "staging")
    config_mod._settings = None  # invalidate cached Settings
    settings_staging = get_settings()
    assert settings_staging.env == "staging"

    coordination = CoordinationStore(redis=redis)
    engine = create_async_engine(settings_staging.postgres_dsn, pool_pre_ping=True)
    pg_store = MemoryPostgresStore(engine)
    freshness_pg = FreshnessStore(engine)
    qdrant = MemoryQdrantStore(workspace_id=workspace)

    proc_dev: subprocess.Popen[bytes] | None = None
    proc_staging: subprocess.Popen[bytes] | None = None
    worker_dev = "envtest-worker-dev"
    worker_staging = "envtest-worker-staging"

    try:
        # Seed record.
        rec = MemoryRecord(
            id=record_id,
            workspace_id=workspace,
            agent_id="agent-env",
            scope=MemoryScope.PER_AGENT,
            source_type="env_prefix_test",
            content="Env prefix isolation record",
            content_hash=f"env-{record_id}",
        )
        await pg_store.save(rec)
        await qdrant.upsert(rec)

        # Enqueue under env=staging — the job lands on
        # freshness:staging:queue:{workspace}.
        await coordination.enqueue_job(
            FreshnessJob(
                workspace_id=workspace,
                event_type="knowledge_changed",
                target_kind="memory_record",
                target_id=record_id,
            )
        )
        staging_depth = await coordination.queue_depth(workspace)
        assert staging_depth == 1

        # Spawn a development worker — must NOT see the staging job.
        proc_dev = _spawn_worker("development", worker_dev)

        # Wait 8 seconds; assert no ``freshness_job_received`` event yet.
        saw_event = await _wait_for_event(
            freshness_pg,
            workspace,
            record_id,
            event_type="freshness_job_received",
            timeout_s=8.0,
        )
        assert saw_event is False, "development worker processed a staging job"

        # Staging queue still holds it.
        staging_depth_after_dev = await coordination.queue_depth(workspace)
        assert staging_depth_after_dev == 1

        # Now spawn a staging worker — it processes the job.
        proc_staging = _spawn_worker("staging", worker_staging)

        processed = await _wait_for_event(
            freshness_pg,
            workspace,
            record_id,
            event_type="freshness_job_processed",
            timeout_s=30.0,
        )
        assert processed is True, "staging worker did not process the seeded job"
    finally:
        for p in (proc_dev, proc_staging):
            if p is not None:
                try:
                    p.send_signal(signal.SIGTERM)
                    p.wait(timeout=5)
                except Exception:
                    with contextlib.suppress(Exception):
                        p.kill()
        await _cleanup_pg(engine, workspace)
        # Wipe any residual freshness keys under both env prefixes.
        for env_name in ("staging", "development"):
            key = f"freshness:{env_name}:queue:{workspace}"
            with contextlib.suppress(Exception):
                await redis.delete(key)
        # Cleanup per-worker processing lists + heartbeats.
        from metronix.freshness.coordination import (
            _heartbeat_key,
            _reclaim_lock_key,
            processing_key_for,
        )

        for wid in (worker_dev, worker_staging):
            for key_fn in (processing_key_for, _heartbeat_key, _reclaim_lock_key):
                with contextlib.suppress(Exception):
                    await redis.delete(key_fn(wid))
        if hasattr(qdrant, "close"):
            with contextlib.suppress(Exception):
                await qdrant.close()
        await redis.close()
        await engine.dispose()
