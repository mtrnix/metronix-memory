"""FreshnessMonitor — applies time-based lifecycle rules (MTRNIX-313).

Phase B: generic over the target kind via :class:`FreshnessTarget`. Was
``metatron.memory.freshness.monitor`` in Phase A.

Priority order (first match wins):

1. ``valid_until <= now``   → ``ARCHIVED`` (score 0.0)
2. ``superseded_by`` present → ``SUPERSEDED`` (score 0.1)
3. ``updated_at`` older than ``stale_after_days`` AND
   ``last_freshness_run_at`` is set → ``STALE`` (score 0.25).

**Age-gate (Phase B, MTRNIX-313):** the STALE rule only fires when
``last_freshness_run_at`` is non-null. On the very first run for a target,
the monitor only records ``last_freshness_run_at=now`` and returns. This
prevents a bulk STALE avalanche on day one when many pre-existing rows
cross the threshold simultaneously.

After any lifecycle transition, the Monitor calls
:meth:`FreshnessTarget.sync_downstream_stores` so derived stores (Qdrant
chunk payloads, Neo4j Document nodes for KB) mirror the new status.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import LifecycleStatus, MachineEvent

if TYPE_CHECKING:
    from metatron.freshness.coordination import CoordinationStore
    from metatron.freshness.targets import FreshnessTarget
    from metatron.storage.freshness_pg import FreshnessStore

logger = structlog.get_logger()


class FreshnessMonitor:
    """Applies freshness lifecycle rules to a single record."""

    STAGE = "monitor"

    def __init__(
        self,
        *,
        target: FreshnessTarget,
        freshness_store: FreshnessStore,
        coordination: CoordinationStore,
        stale_after_days: int = 30,
        lock_ttl: int = 30,
    ) -> None:
        self._target = target
        self._freshness_store = freshness_store
        self._coord = coordination
        self._stale_after_days = stale_after_days
        self._lock_ttl = lock_ttl

    async def run(self, workspace_id: str, target_id: str) -> LifecycleStatus | None:
        """Evaluate lifecycle rules. Returns the new status if changed."""
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

            now = datetime.now(UTC)
            new_status: LifecycleStatus | None = None
            new_score = record.freshness_score

            if record.valid_until is not None and record.valid_until <= now:
                new_status = LifecycleStatus.ARCHIVED
                new_score = 0.0
            elif record.superseded_by:
                new_status = LifecycleStatus.SUPERSEDED
                new_score = 0.1
            elif record.updated_at is not None and record.updated_at <= now - timedelta(
                days=self._stale_after_days
            ):
                # Age-gate (MTRNIX-313) — applies to targets that persist
                # ``last_freshness_run_at`` (KB raw_documents). On the very
                # first evaluation for such a target we only stamp the
                # timestamp and return; subsequent runs apply STALE. For
                # memory records (which do not persist the stamp in Phase B)
                # we preserve Phase A behaviour: STALE fires on the first
                # run across the threshold.
                age_gated = target_kind != "memory_record" and record.last_freshness_run_at is None
                if age_gated:
                    await self._target.update_lifecycle(
                        workspace_id,
                        target_id,
                        last_freshness_run_at=now,
                    )
                    return None
                new_status = LifecycleStatus.STALE
                new_score = 0.25

            if new_status is None:
                # No rule fires — leave the record untouched so Phase A
                # behaviour is preserved for memory records that were never
                # stale. The age-gate only writes ``last_freshness_run_at``
                # in the "stale-rule first-touch" branch above.
                return None

            await self._target.update_lifecycle(
                workspace_id,
                target_id,
                status=new_status,
                freshness_score=new_score,
                last_freshness_run_at=now,
            )
            # Mirror the transition into derived stores (Qdrant chunk
            # payloads, Neo4j status). Best-effort; the adapter swallows.
            await self._target.sync_downstream_stores(
                workspace_id,
                target_id,
                status=new_status,
                freshness_score=new_score,
            )
            await self._freshness_store.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_kind=target_kind,
                    target_id=target_id,
                    payload={
                        "stage": self.STAGE,
                        "status": new_status.value,
                        "freshness_score": new_score,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    },
                )
            )
            return new_status
        finally:
            await self._coord.release(self.STAGE, target_id, token, target_kind=target_kind)
