"""Producer hook — called by writers to enqueue freshness jobs (MTRNIX-304).

Design goals:
* **Flag-gated.** When ``freshness_enabled=False`` the call is a no-op —
  zero Redis traffic so pre-MTRNIX-304 callers behave byte-identically.
* **Fail-soft.** Redis errors are logged, never raised. Producing a job
  must not break ``memory_store`` / ``memory_update`` / ``memory_promote``.
* **Stateless construction.** ``_build_default_coordination`` lazily
  instantiates a ``RedisStore`` from the global ``Settings`` — callers
  that already hold a coordination store can pass it in explicitly.
"""

from __future__ import annotations

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob
from metatron.memory.freshness.coordination import CoordinationStore

logger = structlog.get_logger()

# Lazy singleton cache so the first enqueue in a hot path avoids a fresh
# Redis connection handshake on every call.
_default_store: CoordinationStore | None = None


def _build_default_coordination() -> CoordinationStore:
    """Build (or reuse) the default CoordinationStore against Settings.redis_url."""
    global _default_store  # noqa: PLW0603
    if _default_store is None:
        from metatron.storage.redis import RedisStore

        settings = get_settings()
        redis = RedisStore(settings.redis_url)
        _default_store = CoordinationStore(redis=redis)
    return _default_store


def _reset_default_for_tests() -> None:
    """Clear the cached default store (test helper)."""
    global _default_store  # noqa: PLW0603
    _default_store = None


async def enqueue_if_enabled(
    workspace_id: str,
    record_id: str,
    event_type: str = "knowledge_changed",
    *,
    coordination: CoordinationStore | None = None,
    payload: dict[str, str] | None = None,
) -> None:
    """Enqueue a freshness job when the feature is enabled.

    Args:
        workspace_id: Tenant id — the job lives on that workspace's queue.
        record_id: Target ``MemoryRecord.id``.
        event_type: Logical reason for the event (``knowledge_changed``,
            ``content_changed``, ``metadata_changed``, ``knowledge_deleted``,
            ``scope_changed``, ``scheduled_scan``).
        coordination: Optional DI override (tests, integration).
        payload: Optional extra context forwarded to the worker.
    """
    settings = get_settings()
    if not settings.freshness_enabled:
        return
    if not workspace_id or not record_id:
        # Producer must be defensive — if the caller has no IDs, silently
        # drop: the worker cannot do anything with an empty target.
        return
    try:
        store = coordination or _build_default_coordination()
        job = FreshnessJob(
            workspace_id=workspace_id,
            event_type=event_type,
            target_kind="memory_record",
            target_id=record_id,
            payload=dict(payload or {}),
        )
        await store.enqueue_job(job)
    except Exception:
        logger.warning(
            "freshness.producer.enqueue_failed",
            workspace_id=workspace_id,
            record_id=record_id,
            event_type=event_type,
            exc_info=True,
        )
