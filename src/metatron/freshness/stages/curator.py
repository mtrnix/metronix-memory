"""Curator stage — promotes supported candidates to ACTIVE (MTRNIX-313).

Phase B: generic over the target kind via :class:`FreshnessTarget`. Was
``metatron.memory.freshness.curator`` in Phase A.

A ``CANDIDATE`` record with ``evidence_count >= 1`` is promoted to
``ACTIVE`` and tagged ``auto_curated``. Records already in other statuses
are left alone (idempotent).

KB targets (``supports_candidate_promotion = False``) short-circuit this
stage entirely: Phase B has no CANDIDATE state for raw_documents, so the
Curator does nothing for KB jobs and never acquires a lock.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import LifecycleStatus, MachineEvent

if TYPE_CHECKING:
    from metatron.freshness.coordination import CoordinationStore
    from metatron.freshness.targets import FreshnessTarget
    from metatron.storage.freshness_pg import FreshnessStore

logger = structlog.get_logger()


class Curator:
    """Promotes candidate records to ACTIVE when they have evidence."""

    STAGE = "curator"
    AUTO_CURATED_TAG = "auto_curated"

    def __init__(
        self,
        *,
        target: FreshnessTarget,
        freshness_store: FreshnessStore,
        coordination: CoordinationStore,
        lock_ttl: int = 30,
    ) -> None:
        self._target = target
        self._freshness_store = freshness_store
        self._coord = coordination
        self._lock_ttl = lock_ttl

    async def run(self, workspace_id: str, target_id: str) -> LifecycleStatus | None:
        """Promote a CANDIDATE with evidence to ACTIVE.

        Returns the new status when a transition happens, else ``None``.
        KB targets short-circuit immediately (no CANDIDATE state).
        """
        if not self._target.supports_candidate_promotion:
            return None

        target_kind = self._target.kind
        token = await self._coord.acquire_lock(
            self.STAGE,
            target_id,
            self._lock_ttl,
            target_kind=target_kind,
        )
        if token is None:
            return None

        started = time.monotonic()
        try:
            record = await self._target.get(workspace_id, target_id)
            if record is None:
                return None

            if record.status != LifecycleStatus.CANDIDATE:
                return None
            if record.evidence_count < 1:
                return None

            await self._target.update_lifecycle(
                workspace_id,
                target_id,
                status=LifecycleStatus.ACTIVE,
                append_tag=self.AUTO_CURATED_TAG,
            )
            # MTRNIX-322: mirror the PG ACTIVE transition onto derived stores
            # (memory → Qdrant payload; KB no-ops today). Best-effort — the
            # adapter swallows failures and increments the Prometheus
            # ``freshness_qdrant_sync_failed_total`` counter.
            await self._target.sync_downstream_stores(
                workspace_id,
                target_id,
                status=LifecycleStatus.ACTIVE,
                freshness_score=record.freshness_score or 0.5,
            )
            await self._freshness_store.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_kind=target_kind,
                    target_id=target_id,
                    payload={
                        "stage": self.STAGE,
                        "status": LifecycleStatus.ACTIVE.value,
                        "tag_added": self.AUTO_CURATED_TAG,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    },
                )
            )
            return LifecycleStatus.ACTIVE
        finally:
            await self._coord.release(self.STAGE, target_id, token, target_kind=target_kind)
