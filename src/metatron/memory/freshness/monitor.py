"""FreshnessMonitor — applies time-based lifecycle rules (MTRNIX-304).

Priority order (first match wins):

1. ``valid_until <= now``   → ``ARCHIVED`` (score 0.0)
2. ``superseded_by`` present → ``SUPERSEDED`` (score 0.1)
3. ``updated_at`` older than ``stale_after_days`` → ``STALE`` (score 0.25)
4. Otherwise: no-op.

No Neo4j writes here — the monitor only updates PG lifecycle columns.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import MachineEvent, MemoryStatus

if TYPE_CHECKING:
    from metatron.memory.freshness.coordination import CoordinationStore
    from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
    from metatron.storage.memory_postgres import MemoryPostgresStore

logger = structlog.get_logger()


class FreshnessMonitor:
    """Applies freshness lifecycle rules to a single record."""

    STAGE = "monitor"

    def __init__(
        self,
        *,
        pg_store: MemoryPostgresStore,
        freshness_pg: FreshnessPostgresStore,
        coordination: CoordinationStore,
        stale_after_days: int = 30,
        lock_ttl: int = 30,
    ) -> None:
        self._pg = pg_store
        self._freshness_pg = freshness_pg
        self._coord = coordination
        self._stale_after_days = stale_after_days
        self._lock_ttl = lock_ttl

    async def run(self, workspace_id: str, record_id: str) -> MemoryStatus | None:
        """Evaluate lifecycle rules. Returns the new status if changed."""
        token = await self._coord.acquire_lock(self.STAGE, record_id, self._lock_ttl)
        if token is None:
            return None

        started = time.monotonic()
        try:
            record = await self._pg.get(workspace_id, record_id)
            if record is None:
                return None

            now = datetime.now(UTC)
            new_status: MemoryStatus | None = None
            new_score = record.freshness_score

            if record.valid_until is not None and record.valid_until <= now:
                new_status = MemoryStatus.ARCHIVED
                new_score = 0.0
            elif record.superseded_by:
                new_status = MemoryStatus.SUPERSEDED
                new_score = 0.1
            elif record.updated_at is not None and record.updated_at <= now - timedelta(
                days=self._stale_after_days
            ):
                new_status = MemoryStatus.STALE
                new_score = 0.25

            if new_status is None:
                return None

            await self._pg.update_lifecycle(
                workspace_id,
                record_id,
                status=new_status,
                freshness_score=new_score,
            )
            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_id=record_id,
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
            await self._coord.release(self.STAGE, record_id, token)
