from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.responses import FileResponse

from metronix.api.dependencies import resolve_workspace_id
from metronix.export.models import ExportScope

router = APIRouter(prefix="/export", tags=["export"])


class ExportStartRequest(BaseModel):
    workspace_id: str | None = None
    all_workspaces: bool = False


def _service(request: Request) -> Any:
    svc = getattr(request.app.state, "export_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="export service unavailable")
    return svc


def _token_store(request: Request) -> Any:
    store = getattr(request.app.state, "export_token_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="export service unavailable")
    return store


def _absolutize(request: Request, result: dict[str, Any]) -> dict[str, Any]:
    # When public_base_url is unset the service emits a relative download_url;
    # the REST surface can fill in the host from the request itself.
    url = result.get("download_url")
    if isinstance(url, str) and url.startswith("/"):
        result["download_url"] = str(request.base_url).rstrip("/") + url
    return result


def _allowed_workspaces(request: Request) -> list[str]:
    user = getattr(request.state, "user", {}) or {}
    allowed = user.get("workspace_ids", [])
    return allowed if isinstance(allowed, list) else []


def _is_admin(request: Request) -> bool:
    return "*" in _allowed_workspaces(request)


def _authorize_job_access(request: Request, scope: ExportScope) -> None:
    """A caller may read an export only if they can access its scope.

    all_workspaces exports are admin-only; single-workspace exports require the
    caller to have access to that workspace. Without this, any authenticated user
    could poll any export_id and receive a download token (cross-workspace leak).
    """
    if _is_admin(request):
        return
    if scope.all_workspaces or scope.workspace_id not in _allowed_workspaces(request):
        raise HTTPException(status_code=403, detail="no access to this export")


@router.post("")
async def start_export(
    body: ExportStartRequest,
    request: Request,
    workspace_id: Annotated[str, Depends(resolve_workspace_id)],
) -> dict[str, Any]:
    if body.all_workspaces and not _is_admin(request):
        raise HTTPException(status_code=403, detail="all_workspaces requires admin access")
    scope = ExportScope(
        all_workspaces=body.all_workspaces,
        workspace_id=None if body.all_workspaces else (body.workspace_id or workspace_id),
    )
    job = await _service(request).start(scope)
    return {"export_id": job.id, "status": str(job.status)}


@router.get("/{export_id}")
async def export_status(
    export_id: str,
    request: Request,
    _ws: Annotated[str, Depends(resolve_workspace_id)],
) -> dict[str, Any]:
    service = _service(request)
    job = await service.get_job(export_id)
    if job is None:
        raise HTTPException(status_code=404, detail="export not found")
    _authorize_job_access(request, job.scope)
    result = await service.status(export_id)
    if result is None:
        raise HTTPException(status_code=404, detail="export not found")
    return _absolutize(request, result)


@router.get("/{export_id}/download")
async def download_export(
    export_id: str,
    request: Request,
    token: str = Query(..., min_length=8),
) -> FileResponse:
    """Token-only download. No JWT/API-key. Consumes the one-time token."""
    store = _token_store(request)
    # Validate (and check the file) BEFORE consuming, so a swept/missing archive
    # does not burn the token and force a full re-export.
    entry = await store.peek(token)
    if entry is None or entry.get("export_id") != export_id:
        raise HTTPException(status_code=404, detail="invalid or expired token")
    path = entry.get("path") or ""
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=410, detail="export archive no longer available")
    # Atomic one-time consume: the loser of a concurrent download gets None.
    consumed = await store.consume(token)
    if consumed is None or consumed.get("export_id") != export_id:
        raise HTTPException(status_code=404, detail="invalid or expired token")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"metronix-export-{export_id}.zip",
    )
