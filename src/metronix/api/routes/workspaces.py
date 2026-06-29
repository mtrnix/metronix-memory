"""Workspaces CRUD API — /api/v1/workspaces.

Migrated from PoC metronix/api_workspaces.py.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from metronix.workspaces import get_workspace_manager

logger = structlog.get_logger()

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    user_id: str = Field("user")
    workspace_id: str | None = None


class WorkspaceResponse(BaseModel):
    workspace_id: str
    name: str
    description: str | None = None
    created_at: str
    user_id: str
    is_active: bool
    config: dict[str, Any] | None = None


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]
    count: int


class WorkspaceStatsResponse(BaseModel):
    workspace_id: str
    name: str
    file_count: int = 0
    chunk_count: int = 0
    entity_count: int = 0
    jira_issue_count: int = 0
    last_upload_time: str | None = None


class ActivateResponse(BaseModel):
    workspace_id: str
    name: str
    status: str


@router.get("/", response_model=WorkspaceListResponse)
def list_workspaces(user_id: str | None = Query("user")) -> WorkspaceListResponse:
    """List all workspaces."""
    manager = get_workspace_manager()
    workspaces = manager.list_workspaces(user_id=user_id)

    # Get active workspace for this user
    active_workspace = manager.get_active_workspace(user_id or "user")
    active_workspace_id = active_workspace.workspace_id

    # Mark only the active workspace as is_active=True
    workspace_responses = []
    for ws in workspaces:
        ws_dict = ws.to_dict()
        ws_dict["is_active"] = ws.workspace_id == active_workspace_id
        workspace_responses.append(WorkspaceResponse(**ws_dict))

    return WorkspaceListResponse(
        workspaces=workspace_responses,
        count=len(workspaces),
    )


@router.post("/", response_model=WorkspaceResponse, status_code=201)
def create_workspace(body: WorkspaceCreate) -> WorkspaceResponse:
    """Create a new workspace."""
    manager = get_workspace_manager()
    try:
        workspace = manager.create_workspace(
            name=body.name,
            description=body.description,
            user_id=body.user_id,
            workspace_id=body.workspace_id,
        )
        return WorkspaceResponse(**workspace.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: str) -> WorkspaceResponse:
    """Get workspace details."""
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    return WorkspaceResponse(**workspace.to_dict())


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str, user_id: str = Query("user")) -> dict[str, str]:
    """Delete a workspace and all its data."""
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")

    try:
        deleted = manager.delete_workspace(workspace_id)
        if not deleted:
            raise HTTPException(status_code=400, detail="Failed to delete workspace")

        errors = []
        try:
            from metronix.storage.qdrant import get_hybrid_store

            store = get_hybrid_store(workspace_id)
            store.delete()
        except Exception as e:
            logger.error("api.workspace.delete.qdrant.error", error=str(e))
            errors.append(f"Qdrant: {e}")

        try:
            from metronix.storage.neo4j_graph import delete_workspace_graph

            delete_workspace_graph(workspace_id)
        except Exception as e:
            logger.error("api.workspace.delete.neo4j.error", error=str(e))
            errors.append(f"Memgraph: {e}")

        if errors:
            raise HTTPException(
                status_code=500,
                detail=f"Workspace deleted but cleanup failed: {'; '.join(errors)}",
            )
        return {"status": "deleted", "workspace_id": workspace_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{workspace_id}/activate", response_model=ActivateResponse)
def activate_workspace(
    workspace_id: str,
    user_id: str = Query("user"),
) -> ActivateResponse:
    """Set active workspace for a user."""
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    success = manager.set_active_workspace(user_id, workspace_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to activate workspace")
    return ActivateResponse(workspace_id=workspace_id, name=workspace.name, status="activated")


@router.get("/{workspace_id}/stats", response_model=WorkspaceStatsResponse)
def get_workspace_stats(workspace_id: str) -> WorkspaceStatsResponse:
    """Get workspace statistics."""
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")

    base_stats = manager.get_workspace_stats(workspace_id)
    file_count = chunk_count = entity_count = jira_issue_count = 0

    try:
        from metronix.storage.qdrant import get_hybrid_store

        store = get_hybrid_store(workspace_id)
        qdrant_stats = store.get_stats()
        file_count = qdrant_stats.get("file_count", 0)
        chunk_count = qdrant_stats.get("chunk_count", 0)
    except Exception as e:
        logger.warning("api.workspace.stats.qdrant.error", error=str(e))

    try:
        from metronix.storage.neo4j_graph import get_graph_driver

        driver = get_graph_driver()
        with driver.session() as session:
            r = session.run(
                "MATCH (e:Entity) WHERE e.workspace_id = $ws RETURN count(e)",
                {"ws": workspace_id},
            )
            rec = r.single()
            entity_count = rec[0] if rec else 0
            r = session.run(
                "MATCH (j:JiraIssue) WHERE j.workspace_id = $ws RETURN count(j)",
                {"ws": workspace_id},
            )
            rec = r.single()
            jira_issue_count = rec[0] if rec else 0
    except Exception as e:
        logger.warning("api.workspace.stats.neo4j.error", error=str(e))

    return WorkspaceStatsResponse(
        workspace_id=workspace_id,
        name=workspace.name,
        file_count=file_count,
        chunk_count=chunk_count,
        entity_count=entity_count,
        jira_issue_count=jira_issue_count,
        last_upload_time=base_stats.last_upload_time,
    )
