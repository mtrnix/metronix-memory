"""Redis coordination primitives for the freshness pipeline.

Moved from ``metatron.memory.freshness.coordination`` in Phase B (MTRNIX-313)
since the queue and locks serve both memory and KB pipelines. Reworked in
MTRNIX-316 to add:

* Env-prefixed keys (``freshness:{env}:...``) so dev rigs sharing a Redis
  instance do not collide. When ``settings.env`` is empty the unprefixed
  Phase A shape is preserved byte-for-byte.
* Per-worker processing list — ``dequeue_batch`` now ``LMOVE``s items into
  ``freshness:{env}:processing:{worker_id}``. Workers SIGKILLed mid-batch
  leave their processing list intact; a periodic reclaim pass (driven by
  ``FreshnessWorker._reclaim_all_orphans``) moves the items back to the
  workspace queue.
* Worker heartbeat — each iteration ``tick_heartbeat`` upserts
  ``freshness:{env}:heartbeat:{worker_id}`` with TTL so the reclaim pass
  can tell live workers from crashed ones.
* ``drain_legacy_unprefixed`` — one-shot migration helper that moves any
  pre-MTRNIX-316 ``freshness:queue:*`` lists into their env-prefixed
  equivalents. Flag-gated in the worker via ``freshness_drain_legacy_at_startup``.

Key shape summary (``{env}`` is empty when ``METATRON_ENV`` is unset):

================  =================================================
Queue             ``freshness:{env}:queue:{workspace_id}``
Processing list   ``freshness:{env}:processing:{worker_id}``
Heartbeat         ``freshness:{env}:heartbeat:{worker_id}``
Reclaim lock      ``freshness:{env}:reclaim_lock:{worker_id}``
Stage lock (mem)  ``freshness:{env}:{stage}:{target_id}``
Stage lock (KB)   ``freshness:{env}:{stage}:{target_kind}:{target_id}``
================  =================================================

Workspace isolation: enqueue/dequeue always take ``workspace_id``; the
worker enumerates queues via ``list_active_workspaces`` and never falls
back to a shared queue. Processing lists are per-worker but each
serialised job still carries its own ``workspace_id`` — reclaim uses that
to route the item back to the correct workspace queue.

Locks use token-guarded Lua scripts via ``RedisStore`` so a worker cannot
release or refresh a lock held by another worker.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import warnings
from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob
from metatron.freshness import metrics

if TYPE_CHECKING:
    from metatron.storage.redis import RedisStore

logger = structlog.get_logger()


_MEMORY_TARGET_KIND = "memory_record"
_LEGACY_QUEUE_PREFIX = "freshness:queue:"


def _key_prefix() -> str:
    """Return the env-namespaced key prefix.

    When ``settings.env`` is unset or empty, returns ``"freshness:"`` — the
    Phase A shape. Otherwise ``"freshness:{env}:"`` so multiple dev rigs
    sharing a single Redis instance stay isolated.
    """
    env = getattr(get_settings(), "env", "") or ""
    if env:
        return f"freshness:{env}:"
    return "freshness:"


def queue_key_for(workspace_id: str) -> str:
    """Return the Redis list key holding pending jobs for a workspace."""
    return f"{_key_prefix()}queue:{workspace_id}"


def processing_key_for(worker_id: str) -> str:
    """Return the per-worker processing list key (MTRNIX-316)."""
    return f"{_key_prefix()}processing:{worker_id}"


def _heartbeat_key(worker_id: str) -> str:
    return f"{_key_prefix()}heartbeat:{worker_id}"


def _reclaim_lock_key(worker_id: str) -> str:
    return f"{_key_prefix()}reclaim_lock:{worker_id}"


def _lock_key(stage: str, target_id: str, target_kind: str = "") -> str:
    """Build the per-stage/per-target lock key.

    Backward-compat shape: when ``target_kind`` is empty or
    ``"memory_record"`` the suffix matches Phase A (no target_kind token)
    so memory callers keep the same wire format. KB callers must pass
    ``target_kind="raw_document"`` to get a target-discriminated key.
    """
    prefix = _key_prefix()
    if not target_kind or target_kind == _MEMORY_TARGET_KIND:
        return f"{prefix}{stage}:{target_id}"
    return f"{prefix}{stage}:{target_kind}:{target_id}"


def _serialize_job(job: FreshnessJob) -> str:
    return json.dumps(asdict(job), default=str, sort_keys=True)


def _deserialize_job(raw: str) -> FreshnessJob | None:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("freshness.queue.malformed", raw=raw[:200])
        return None
    try:
        return FreshnessJob(
            workspace_id=str(data.get("workspace_id", "")),
            event_type=str(data.get("event_type", "")),
            target_kind=str(data.get("target_kind", _MEMORY_TARGET_KIND)),
            target_id=str(data.get("target_id", "")),
            payload=dict(data.get("payload") or {}),
        )
    except (TypeError, ValueError):
        logger.warning("freshness.queue.unparseable", raw=raw[:200])
        return None


def _compat_worker_id() -> str:
    """Synthetic worker id used by the Phase A deprecation shim."""
    return f"compat-noworker:{uuid4().hex[:8]}"


def _worker_id_hash(worker_id: str) -> str:
    """4-hex digest of ``worker_id`` — bounded label cardinality."""
    return hashlib.sha1(worker_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:4]


class CoordinationStore:
    """Thin per-pipeline API over ``RedisStore`` primitives."""

    def __init__(self, redis: RedisStore) -> None:
        self._redis = redis

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    async def enqueue_job(self, job: FreshnessJob) -> None:
        """LPUSH a job onto its workspace queue."""
        await self._redis.lpush(queue_key_for(job.workspace_id), _serialize_job(job))

    async def dequeue_batch(
        self,
        workspace_id: str,
        max_items: int,
        *,
        worker_id: str | None = None,
    ) -> list[FreshnessJob]:
        """LMOVE up to ``max_items`` jobs into a per-worker processing list.

        Each call loops up to ``max_items`` times, atomically ``LMOVE``-ing
        one job from the workspace queue (tail) into the per-worker
        processing list (head). Break as soon as the queue is drained.
        Items stay on the processing list until either ``complete_job``
        LREMs them (successful processing) or the reclaim pass LMOVEs them
        back to the queue (worker crash).

        ``worker_id`` is required for production callers. Phase A unit
        tests that still call ``dequeue_batch(ws, N)`` without the kwarg
        hit a deprecation-warn shim that synthesises a worker id.
        """
        if worker_id is None:
            warnings.warn(
                "dequeue_batch without worker_id is deprecated — pass "
                "worker_id=<build_worker_id()> (MTRNIX-316).",
                DeprecationWarning,
                stacklevel=2,
            )
            worker_id = _compat_worker_id()

        if max_items <= 0:
            return []

        q_key = queue_key_for(workspace_id)
        p_key = processing_key_for(worker_id)
        jobs: list[FreshnessJob] = []
        for _ in range(max_items):
            raw = await self._redis.lmove_rightleft(q_key, p_key)
            if raw is None:
                break
            parsed = _deserialize_job(raw)
            if parsed is not None:
                jobs.append(parsed)
            # Poison items (parsed is None) are already on the processing
            # list; the reclaim pass's poison branch drops them via LREM.
        return jobs

    async def complete_job(self, worker_id: str, job: FreshnessJob) -> None:
        """Remove a successfully-processed job from the worker's processing list.

        Called from the worker's ``finally`` so the LREM runs even on
        pipeline errors. Best-effort — Redis failures are logged and
        swallowed (the reclaim pass picks up orphans).
        """
        try:
            await self._redis.lrem(processing_key_for(worker_id), _serialize_job(job), count=1)
        except Exception:
            logger.warning(
                "freshness.coordination.complete_job_failed",
                worker_id=worker_id,
                workspace_id=job.workspace_id,
                target_id=job.target_id,
                exc_info=True,
            )

    async def queue_depth(self, workspace_id: str) -> int:
        return await self._redis.llen(queue_key_for(workspace_id))

    async def list_active_workspaces(self) -> list[str]:
        """Return the set of workspace_ids that currently have jobs queued."""
        prefix = f"{_key_prefix()}queue:"
        keys = await self._redis.scan_keys(f"{prefix}*")
        return [k[len(prefix) :] for k in keys]

    async def list_processing_workers(self) -> list[str]:
        """Return worker ids that currently own a processing list (MTRNIX-316).

        Graceful degradation: on any Redis failure return ``[]`` so the
        reclaim pass degrades to a no-op for this iteration and retries
        later.
        """
        prefix = f"{_key_prefix()}processing:"
        try:
            keys = await self._redis.scan_keys(f"{prefix}*")
        except Exception:
            logger.warning("freshness.coordination.list_workers_failed", exc_info=True)
            return []
        return [k[len(prefix) :] for k in keys]

    # ------------------------------------------------------------------
    # Worker heartbeat (MTRNIX-316)
    # ------------------------------------------------------------------

    async def tick_heartbeat(self, worker_id: str, ttl: int) -> None:
        """Upsert the per-worker heartbeat key with TTL (best-effort)."""
        try:
            await self._redis.set(_heartbeat_key(worker_id), worker_id, ttl=ttl)
        except Exception:
            logger.warning(
                "freshness.coordination.heartbeat_failed",
                worker_id=worker_id,
                exc_info=True,
            )

    async def is_worker_alive(self, worker_id: str) -> bool:
        """Return True iff the worker's heartbeat key exists (fail-closed)."""
        try:
            return bool(await self._redis.exists(_heartbeat_key(worker_id)))
        except Exception:
            logger.warning(
                "freshness.coordination.is_alive_failed",
                worker_id=worker_id,
                exc_info=True,
            )
            return False

    async def release_worker(self, worker_id: str) -> None:
        """Delete the worker's heartbeat key on graceful shutdown (best-effort)."""
        try:
            await self._redis.delete(_heartbeat_key(worker_id))
        except Exception:
            logger.warning(
                "freshness.coordination.release_worker_failed",
                worker_id=worker_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Orphan reclaim (MTRNIX-316)
    # ------------------------------------------------------------------

    async def reclaim_worker_orphans(self, worker_id: str) -> int:
        """Drain a dead worker's processing list back to its workspace queues.

        Workflow:

        1. Skip if the worker is still alive (heartbeat key present).
        2. Acquire a short-TTL reclaim lock on the worker so two live
           reclaimers do not step on each other.
        3. Peek the tail, parse the workspace_id, then ``LMOVE`` the tail
           back onto that workspace's queue. Repeat until empty.

        Returns the count of jobs recovered. Poison entries (undeserialisable)
        are dropped via LREM so they cannot loop forever.
        """
        if await self.is_worker_alive(worker_id):
            return 0

        lock_key = _reclaim_lock_key(worker_id)
        token = uuid4().hex
        if not await self._redis.acquire_lock(lock_key, 30, token):
            return 0

        recovered = 0
        p_key = processing_key_for(worker_id)
        settings = get_settings()
        env_label = settings.env or ""
        wid_hash = _worker_id_hash(worker_id)
        try:
            while True:
                raw = await self._redis.peek_tail(p_key)
                if raw is None:
                    break
                job = _deserialize_job(raw)
                if job is None:
                    # Poison — drop from processing list to avoid infinite loop.
                    try:
                        await self._redis.lrem(p_key, raw, count=1)
                    except Exception:
                        logger.warning(
                            "freshness.reclaim.poison_lrem_failed",
                            worker_id=worker_id,
                            exc_info=True,
                        )
                        break
                    continue
                dst = queue_key_for(job.workspace_id)
                moved = await self._redis.lmove_rightleft(p_key, dst)
                if moved is None:
                    # Race: the tail moved between peek and LMOVE. Exit
                    # cleanly — the next iteration of the reclaim pass
                    # will revisit if there's still work.
                    break
                recovered += 1
                with contextlib.suppress(Exception):
                    metrics.orphans_reclaimed.labels(env=env_label, worker_id_hash=wid_hash).inc()
        finally:
            await self._redis.release_lock(lock_key, token)

        return recovered

    # ------------------------------------------------------------------
    # Legacy key drain (MTRNIX-316)
    # ------------------------------------------------------------------

    async def drain_legacy_unprefixed(self) -> int:
        """One-shot migration: move unprefixed ``freshness:queue:*`` into env keys.

        No-op when ``settings.env`` is empty (the unprefixed shape IS the
        current shape). Called at worker startup when
        ``freshness_drain_legacy_at_startup=True``. Safe to call repeatedly
        — the second call finds empty legacy lists.
        """
        settings = get_settings()
        env = settings.env or ""
        if not env:
            return 0
        # Scan only the unprefixed shape. Filter out any keys that happen
        # to start with an env-prefixed pattern (paranoia — a key like
        # ``freshness:queue:ws-development:queue:foo`` would not match, but
        # we still defend against exotic workspace ids).
        try:
            all_keys = await self._redis.scan_keys(f"{_LEGACY_QUEUE_PREFIX}*")
        except Exception:
            logger.warning("freshness.legacy.drain.scan_failed", exc_info=True)
            return 0
        legacy_keys = [
            k for k in all_keys if k.count(":") == 2 and not k.startswith(f"freshness:{env}:")
        ]
        moved = 0
        for k in legacy_keys:
            ws = k.split(":", 2)[2]
            new_key = queue_key_for(ws)
            # Drain src → dst. LMOVE RIGHT → LEFT means we take the
            # oldest item and push it to the head of the new queue, so
            # worker FIFO order is preserved (next RIGHT pop from the new
            # queue picks up the oldest).
            while True:
                try:
                    v = await self._redis.lmove_rightleft(k, new_key)
                except Exception:
                    logger.warning(
                        "freshness.legacy.drain.lmove_failed",
                        legacy_key=k,
                        exc_info=True,
                    )
                    break
                if v is None:
                    break
                moved += 1
        if moved:
            with contextlib.suppress(Exception):
                metrics.legacy_keys_drained.labels(env=env).inc(moved)
            logger.info("freshness.legacy.drain.done", moved=moved, env=env)
        return moved

    # ------------------------------------------------------------------
    # Locks
    # ------------------------------------------------------------------

    async def acquire_lock(
        self,
        stage: str,
        target_id: str,
        ttl: int,
        *,
        target_kind: str = "",
    ) -> str | None:
        """Try to acquire a per-stage-per-target lock. Returns a token or None.

        ``target_kind`` defaults to empty so Phase A memory call sites keep
        the Phase A key shape unchanged. KB call sites must pass
        ``target_kind="raw_document"`` to get a prefixed key.
        """
        token = uuid4().hex
        ok = await self._redis.acquire_lock(_lock_key(stage, target_id, target_kind), ttl, token)
        return token if ok else None

    async def heartbeat(
        self,
        stage: str,
        target_id: str,
        ttl: int,
        token: str,
        *,
        target_kind: str = "",
    ) -> bool:
        """Extend a lock's TTL. Returns False if the token no longer matches."""
        return await self._redis.heartbeat_lock(
            _lock_key(stage, target_id, target_kind), ttl, token
        )

    async def release(
        self,
        stage: str,
        target_id: str,
        token: str,
        *,
        target_kind: str = "",
    ) -> None:
        """Release a lock if still owned by this worker."""
        await self._redis.release_lock(_lock_key(stage, target_id, target_kind), token)
