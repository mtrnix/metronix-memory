"""Redis coordination primitives for the freshness pipeline.

Moved from ``metatron.memory.freshness.coordination`` in Phase B (MTRNIX-313)
since the queue and locks serve both memory and KB pipelines.

Key conventions (kept in this module so producers and workers cannot
disagree on the schema):

* Queue key        — ``freshness:queue:{workspace_id}``
  (one queue per workspace; jobs of both target kinds share it and the
  worker discriminates on ``job.target_kind``)
* Lock key (memory) — ``freshness:{stage}:{target_id}``
  (Phase A key shape, preserved for byte-identical behaviour when memory
  callers omit ``target_kind``)
* Lock key (KB)    — ``freshness:{stage}:{target_kind}:{target_id}``
  (prefixed so memory and KB locks do not collide on a coincidental id)

Workspace isolation: enqueue/dequeue always take ``workspace_id``; the
worker enumerates queues via ``list_active_workspaces`` and never falls
back to a shared queue.

Locks use token-guarded Lua scripts via ``RedisStore`` so a worker cannot
release or refresh a lock held by another worker.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

from metatron.core.models import FreshnessJob

if TYPE_CHECKING:
    from metatron.storage.redis import RedisStore

logger = structlog.get_logger()


_QUEUE_PREFIX = "freshness:queue:"
_LOCK_PREFIX = "freshness:"
_MEMORY_TARGET_KIND = "memory_record"


def queue_key_for(workspace_id: str) -> str:
    """Return the Redis list key holding pending jobs for a workspace."""
    return f"{_QUEUE_PREFIX}{workspace_id}"


def _lock_key(stage: str, target_id: str, target_kind: str = "") -> str:
    """Build the per-stage/per-target lock key.

    Backward-compat shape: when ``target_kind`` is empty or
    ``"memory_record"`` the key matches Phase A exactly so memory callers
    (which pass only ``stage`` and ``target_id``) keep the same wire format.
    KB callers must pass ``target_kind="raw_document"`` to get a prefixed key.
    """
    if not target_kind or target_kind == _MEMORY_TARGET_KIND:
        return f"{_LOCK_PREFIX}{stage}:{target_id}"
    return f"{_LOCK_PREFIX}{stage}:{target_kind}:{target_id}"


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

    async def dequeue_batch(self, workspace_id: str, max_items: int) -> list[FreshnessJob]:
        """Atomic multi-pop from the workspace queue. Skips poison messages."""
        raw_items = await self._redis.rpop_batch(queue_key_for(workspace_id), max_items)
        jobs: list[FreshnessJob] = []
        for raw in raw_items:
            parsed = _deserialize_job(raw)
            if parsed is not None:
                jobs.append(parsed)
        return jobs

    async def queue_depth(self, workspace_id: str) -> int:
        return await self._redis.llen(queue_key_for(workspace_id))

    async def list_active_workspaces(self) -> list[str]:
        """Return the set of workspace_ids that currently have jobs queued."""
        keys = await self._redis.scan_keys(f"{_QUEUE_PREFIX}*")
        return [k[len(_QUEUE_PREFIX) :] for k in keys]

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
