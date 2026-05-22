"""ASOC pilot workspace lifecycle REST endpoints (MTRNIX-352, T2).

# NOTE: ASOC pilot endpoint. Workspace lifecycle is driven by ASOC.
# T4 (MTRNIX-354) will replace require_admin with ASOC-issued JWT verification.
# archive/unarchive removed per grooming 2026-05 (MTRNIX-370); archive = delete.
# ASOC backend should call DELETE /workspace/{id} on project archive events.

Three endpoints:

    POST   /api/v1/workspace/bootstrap          — provision + start bootstrap
    DELETE /api/v1/workspace/{workspace_id}     — cascade teardown (204, idempotent)
    GET    /api/v1/workspace/{workspace_id}/status    — read lifecycle state

Auth: ``require_admin`` (admin-only lifecycle control).
TODO(MTRNIX-354): swap to ASOC-issued JWT middleware once T4 lands.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

from metatron.auth.dependencies import require_admin
from metatron.core.exceptions import (
    WorkspaceLifecycleError,
    WorkspaceStateTransitionError,
)
from metatron.core.models import User  # noqa: TC001 — FastAPI Depends return type

if TYPE_CHECKING:
    from metatron.workspaces.bootstrap.models import BootstrapState
    from metatron.workspaces.bootstrap.store import BootstrapStateStore
    from metatron.workspaces.manager import WorkspaceManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["asoc-workspace"])

_WS_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class BootstrapConfig(BaseModel):
    """ASOC connection parameters for a workspace."""

    url: str
    service_token: str
    project_id: str
    asoc_instance_id: str


class BootstrapRequest(BaseModel):
    """Body for POST /workspace/bootstrap."""

    workspace_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_\-]+$",
    )
    source: Literal["asoc"]
    config: BootstrapConfig


class BootstrapStateResponse(BaseModel):
    """Wire shape returned by state-mutating endpoints + status GET."""

    workspace_id: str
    state: Literal["bootstrapping", "ready", "failed"]
    progress: float
    current_step: str | None
    last_processed_resource: str | None
    last_processed_id: str | None
    indexed_count: int
    total_count: int | None
    last_error: str | None
    last_synced_at: str | None
    retry_count: int
    next_retry_at: str | None
    updated_at: str

    @classmethod
    def from_domain(cls, st: BootstrapState) -> BootstrapStateResponse:
        return cls(
            workspace_id=st.workspace_id,
            state=str(st.state),  # type: ignore[arg-type]
            progress=st.progress,
            current_step=st.current_step,
            last_processed_resource=st.last_processed_resource,
            last_processed_id=st.last_processed_id,
            indexed_count=st.indexed_count,
            total_count=st.total_count,
            last_error=st.last_error,
            last_synced_at=st.last_synced_at.isoformat() if st.last_synced_at else None,
            retry_count=st.retry_count,
            next_retry_at=st.next_retry_at.isoformat() if st.next_retry_at else None,
            updated_at=st.updated_at.isoformat(),
        )


# ---------------------------------------------------------------------------
# DI helpers (pull from app.state)
# ---------------------------------------------------------------------------


def _get_workspace_manager(request: Request) -> WorkspaceManager:
    """Return the ASOC-wired WorkspaceManager from app.state."""
    mgr = getattr(request.app.state, "workspace_manager_async", None)
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="ASOC workspace manager not initialized.",
        )
    return mgr  # type: ignore[no-any-return]


def _get_bootstrap_store(request: Request) -> BootstrapStateStore:
    """Return BootstrapStateStore from app.state."""
    store = getattr(request.app.state, "bootstrap_state_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Bootstrap state store not initialized.",
        )
    return store  # type: ignore[no-any-return]


def _validate_workspace_id_path(workspace_id: str) -> str:
    """Validate path param workspace_id; raise 400 on invalid chars."""
    if not _WS_ID_PATTERN.match(workspace_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid workspace_id '{workspace_id}': "
                "only alphanumeric characters, underscores, and hyphens are allowed."
            ),
        )
    if len(workspace_id) > 255:
        raise HTTPException(
            status_code=400,
            detail=f"workspace_id must not exceed 255 characters (got {len(workspace_id)}).",
        )
    return workspace_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/workspace/bootstrap", status_code=200)
async def bootstrap_workspace(
    body: BootstrapRequest,
    request: Request,
    response: Response,
    _user: Annotated[User, Depends(require_admin)],
) -> BootstrapStateResponse:
    """Provision and start bootstrapping a workspace.

    - 202 if the workspace is newly created (state = bootstrapping).
    - 200 if already bootstrapping or ready (idempotent).
    - 409 if archived (caller must unarchive first).
    """
    store = _get_bootstrap_store(request)
    mgr = _get_workspace_manager(request)

    # Determine 202 vs 200 before calling bootstrap() — check pre-existence.
    pre_existing = await store.get(body.workspace_id)

    try:
        state = await mgr.bootstrap(
            body.workspace_id,
            body.source,
            body.config.model_dump(),
        )
    except WorkspaceStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkspaceLifecycleError as exc:
        logger.exception("workspace.bootstrap.lifecycle_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response.status_code = 202 if pre_existing is None else 200
    return BootstrapStateResponse.from_domain(state)


@router.delete("/workspace/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_\-]+$", max_length=255)],
    request: Request,
    _user: Annotated[User, Depends(require_admin)],
) -> None:
    """Cascade-delete a workspace (idempotent, always 204).

    Cancels in-flight bootstrap, drops Qdrant collection, cleans Neo4j,
    deletes chat threads, and removes the bootstrap_state row.  Best-effort —
    partial failures are logged at WARNING but do not change the response.
    """
    _validate_workspace_id_path(workspace_id)
    mgr = _get_workspace_manager(request)
    await mgr.delete(workspace_id)


@router.get("/workspace/{workspace_id}/status")
async def get_workspace_status(
    workspace_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_\-]+$", max_length=255)],
    request: Request,
    _user: Annotated[User, Depends(require_admin)],
) -> BootstrapStateResponse:
    """Return the current bootstrap lifecycle state.

    - 200 on success.
    - 404 if no bootstrap_state row found.
    """
    _validate_workspace_id_path(workspace_id)
    store = _get_bootstrap_store(request)

    state = await store.get(workspace_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_id}' not found.",
        )
    return BootstrapStateResponse.from_domain(state)
