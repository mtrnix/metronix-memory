"""Curator stage — promotes supported candidates to ACTIVE (MTRNIX-304).

A ``CANDIDATE`` record with ``evidence_count >= 1`` is promoted to
``ACTIVE`` and tagged ``auto_curated``. Records already in other statuses
are left alone (idempotent).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import MachineEvent, MemoryStatus

if TYPE_CHECKING:
    from metatron.memory.freshness.coordination import CoordinationStore
    from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
    from metatron.storage.memory_postgres import MemoryPostgresStore

logger = structlog.get_logger()


class Curator:
    """Promotes candidate memories to ACTIVE when they have evidence."""

    STAGE = "curator"
    AUTO_CURATED_TAG = "auto_curated"

    def __init__(
        self,
        *,
        pg_store: MemoryPostgresStore,
        freshness_pg: FreshnessPostgresStore,
        coordination: CoordinationStore,
        lock_ttl: int = 30,
    ) -> None:
        self._pg = pg_store
        self._freshness_pg = freshness_pg
        self._coord = coordination
        self._lock_ttl = lock_ttl

    async def run(self, workspace_id: str, record_id: str) -> MemoryStatus | None:
        """Promote a CANDIDATE with evidence to ACTIVE.

        Returns the new status when a transition happens, else ``None``.
        """
        token = await self._coord.acquire_lock(self.STAGE, record_id, self._lock_ttl)
        if token is None:
            return None

        started = time.monotonic()
        try:
            record = await self._pg.get(workspace_id, record_id)
            if record is None:
                return None

            if record.status != MemoryStatus.CANDIDATE:
                await self._coord.write_checkpoint(self.STAGE, record_id, "skip_not_candidate")
                return None
            if record.evidence_count < 1:
                await self._coord.write_checkpoint(self.STAGE, record_id, "skip_no_evidence")
                return None

            await self._pg.update_lifecycle(
                workspace_id,
                record_id,
                status=MemoryStatus.ACTIVE,
                append_tag=self.AUTO_CURATED_TAG,
            )
            await self._coord.write_checkpoint(self.STAGE, record_id, "promoted_active")
            await self._freshness_pg.save_machine_event(
                MachineEvent(
                    workspace_id=workspace_id,
                    event_type="freshness_stage_completed",
                    target_id=record_id,
                    payload={
                        "stage": self.STAGE,
                        "status": MemoryStatus.ACTIVE.value,
                        "tag_added": self.AUTO_CURATED_TAG,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                    },
                )
            )
            return MemoryStatus.ACTIVE
        finally:
            await self._coord.release(self.STAGE, record_id, token)
