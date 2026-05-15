"""Bootstrap state models for ASOC workspace lifecycle (MTRNIX-352, T2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class BootstrapStateEnum(StrEnum):
    """Lifecycle states for an ASOC-provisioned workspace."""

    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    ARCHIVED = "archived"
    FAILED = "failed"


@dataclass(frozen=True)
class BootstrapState:
    """Snapshot of a workspace's bootstrap lifecycle row.

    Fields mirror the ``bootstrap_state`` DB table columns exactly so
    callers can roundtrip without lossy conversion.
    """

    workspace_id: str
    state: BootstrapStateEnum
    progress: float
    current_step: str | None
    last_processed_resource: str | None
    last_processed_id: str | None
    indexed_count: int
    total_count: int | None
    last_error: str | None
    last_synced_at: datetime | None
    retry_count: int
    next_retry_at: datetime | None
    updated_at: datetime
