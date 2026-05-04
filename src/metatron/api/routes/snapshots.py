"""Snapshot REST API — /api/v1/snapshots (MTRNIX-272).

Endpoints for restoring and diffing memory snapshots. Listing and creation
live under ``/api/v1/agents/{id}/snapshots`` so the agent context is always
explicit. The cross-snapshot operations live here because the snapshot id is
the natural primary key.

Workspace is always derived from the authenticated user — never accepted from
the request body or query string. A snapshot id from another workspace
resolves to 404.
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from metatron.api.dependencies import get_memory_snapshot_service
from metatron.api.routes.agents import MemorySnapshotResponse, _snapshot_to_response
from metatron.auth.dependencies import require_editor, require_viewer
from metatron.core.exceptions import (
    MemoryNotFoundError,
    SnapshotCorruptError,
    SnapshotOverflowError,
)
from metatron.core.models import User  # noqa: TC001 — FastAPI Annotated DI needs runtime import
from metatron.memory.snapshot import (
    DiffKey,
    MemorySnapshotService,  # noqa: TC001 — FastAPI Annotated DI needs runtime import
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


class RestoreSnapshotResponse(BaseModel):
    """Response body for ``POST /snapshots/{id}/restore``."""

    snapshot_id: str
    pre_restore_snapshot: MemorySnapshotResponse
    restored_count: int


class SnapshotDiffResponse(BaseModel):
    """Response body for ``GET /snapshots/diff``."""

    from_snapshot_id: str
    to_snapshot_id: str
    key: str
    added: list[str]
    removed: list[str]
    changed: list[str]


@router.post(
    "/{snapshot_id}/restore",
    response_model=RestoreSnapshotResponse,
)
async def restore_snapshot(
    snapshot_id: str,
    user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
    snap_service: Annotated[MemorySnapshotService, Depends(get_memory_snapshot_service)],
) -> RestoreSnapshotResponse:
    """Replace the agent's memory with the contents of the snapshot.

    Steps (see :class:`MemorySnapshotService.restore`):

    1. Verify SHA-256 of the snapshot file.
    2. Take an automatic ``pre_restore`` snapshot of current state.
    3. PG ``BEGIN; DELETE; INSERT; COMMIT``.
    4. Best-effort Qdrant + Neo4j cleanup and re-population.
    """
    try:
        pre_restore, restored = await snap_service.restore(snapshot_id)
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except SnapshotOverflowError as exc:
        # The auto pre_restore snapshot tripped the overflow guard — the
        # agent's current memory exceeds the per-snapshot cap, or the file
        # cap was lowered after the original snapshot was written. The
        # restore is aborted before any state changes.
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except SnapshotCorruptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return RestoreSnapshotResponse(
        snapshot_id=snapshot_id,
        pre_restore_snapshot=_snapshot_to_response(pre_restore),
        restored_count=restored,
    )


@router.get("/diff", response_model=SnapshotDiffResponse)
async def diff_snapshots(
    user: Annotated[User, Depends(require_viewer)],  # noqa: ARG001
    snap_service: Annotated[MemorySnapshotService, Depends(get_memory_snapshot_service)],
    from_snapshot_id: Annotated[str, Query(alias="from", min_length=1, max_length=128)],
    to_snapshot_id: Annotated[str, Query(alias="to", min_length=1, max_length=128)],
    key: Literal["source", "content_hash"] = "source",
) -> SnapshotDiffResponse:
    """Compare two snapshots of the same agent.

    Returns ``added`` / ``removed`` / ``changed`` record-id lists. Both
    snapshots must belong to the bound workspace AND share the same
    ``agent_id`` — cross-agent diffs return 400.
    """
    try:
        diff = await snap_service.diff(
            from_snapshot_id,
            to_snapshot_id,
            key=DiffKey(key),
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except SnapshotCorruptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return SnapshotDiffResponse(
        from_snapshot_id=diff.from_snapshot_id,
        to_snapshot_id=diff.to_snapshot_id,
        key=diff.key,
        added=diff.added,
        removed=diff.removed,
        changed=diff.changed,
    )
