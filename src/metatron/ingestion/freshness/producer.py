"""KB producer hook — enqueue freshness jobs after raw_documents writes.

MTRNIX-313 (Phase B): called by the connector sync path after
``upsert_raw_documents`` succeeds. Flag-gated so a deployment with the
master freshness flag on but KB-specific flag off pays zero Redis cost on
the ingestion hot path.

Fail-soft semantics: any exception (Redis unreachable, serialization bug)
is logged and swallowed — KB ingestion must keep working even when the
freshness queue is down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob

if TYPE_CHECKING:
    from metatron.freshness.coordination import CoordinationStore

logger = structlog.get_logger()


_default_store: CoordinationStore | None = None


def _build_default_coordination() -> CoordinationStore:
    """Lazy singleton so the producer path avoids Redis I/O when the flag is off."""
    global _default_store  # noqa: PLW0603
    if _default_store is None:
        from metatron.freshness.coordination import CoordinationStore
        from metatron.storage.redis import RedisStore

        settings = get_settings()
        _default_store = CoordinationStore(redis=RedisStore(settings.redis_url))
    return _default_store


def _reset_default_for_tests() -> None:
    """Test-only reset hook; clears the module-level singleton."""
    global _default_store  # noqa: PLW0603
    _default_store = None


async def enqueue_raw_document_if_enabled(
    workspace_id: str,
    raw_document_id: str,
    event_type: str = "knowledge_changed",
    *,
    coordination: CoordinationStore | None = None,
    payload: dict[str, str] | None = None,
) -> None:
    """Enqueue a freshness job for a raw_document when both flags are on.

    Flag gate: requires ``METATRON_FRESHNESS_ENABLED=true`` **and**
    ``METATRON_FRESHNESS_KB_ENABLED=true``. Either off → no-op.

    Args:
        workspace_id: Tenant id.
        raw_document_id: ``raw_documents.id`` (PK).
        event_type: One of ``knowledge_changed`` (new row), ``content_changed``
            (update of existing row), ``knowledge_deleted``, ``scheduled_scan``.
        coordination: Optional override (tests pass a fake).
        payload: Optional extra metadata embedded into the job payload.
    """
    settings = get_settings()
    if not settings.freshness_enabled or not settings.freshness_kb_enabled:
        return
    if not workspace_id or not raw_document_id:
        return
    try:
        store = coordination or _build_default_coordination()
        job = FreshnessJob(
            workspace_id=workspace_id,
            event_type=event_type,
            target_kind="raw_document",
            target_id=raw_document_id,
            payload=dict(payload or {}),
        )
        await store.enqueue_job(job)
    except Exception:
        logger.warning(
            "freshness.raw_document_producer.enqueue_failed",
            workspace_id=workspace_id,
            raw_document_id=raw_document_id,
            event_type=event_type,
            exc_info=True,
        )
