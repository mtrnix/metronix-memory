"""Knowledge graph visualization API — /api/v1/graph."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, HTTPException, Query
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from pydantic import BaseModel
from starlette.requests import Request

logger = structlog.get_logger()

router = APIRouter(prefix="/graph", tags=["graph"])


async def _resolve_user_groups(request: Request, workspace_id: str) -> list[str] | None:
    """Resolve user_groups from plugin_manager pipeline hooks, if available."""
    user_groups = None
    plugin_manager = getattr(request.app.state, "plugin_manager", None)
    if plugin_manager:
        user_state = getattr(request.state, "user", None)
        user_id = (
            user_state.get("user_id")
            if isinstance(user_state, dict)
            else getattr(user_state, "id", None)
            if user_state
            else None
        )
        if user_id:
            ctx = {"user_id": user_id, "workspace_id": workspace_id}
            for hook in plugin_manager.get_pipeline_hooks("search_pre_filter"):
                ctx = await hook(ctx)
            user_groups = ctx.get("user_groups")
    return user_groups


class GraphNode(BaseModel):
    id: int
    name: str
    type: str | None
    workspace_id: str | None
    connections: int


class GraphEdge(BaseModel):
    source: int
    target: int
    type: str | None
    valid_from: str | None = None
    valid_to: str | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


@router.get("/overview", response_model=GraphResponse)
async def graph_overview(
    request: Request,
    workspace_id: str = Query(..., description="Workspace ID"),
    limit: int = Query(100, ge=1, le=500, description="Max nodes to return"),
) -> GraphResponse:
    """Get top-N most connected entities for initial graph render."""
    from metatron.storage.graph_ops import get_graph_overview

    user_groups = await _resolve_user_groups(request, workspace_id)

    try:
        data = await asyncio.to_thread(
            get_graph_overview,
            workspace_id,
            limit,
            user_groups=user_groups,
        )
    except (ServiceUnavailable, SessionExpired, ConnectionError, BrokenPipeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Graph database unavailable: {exc}")
    except Exception as exc:
        logger.error(
            "api.graph.overview.error",
            workspace_id=workspace_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Graph query failed: {exc}")

    return GraphResponse(
        nodes=[GraphNode(**n) for n in data["nodes"]],
        edges=[GraphEdge(**e) for e in data["edges"]],
        truncated=data["truncated"],
    )


@router.get("/expand/{entity_id}", response_model=GraphResponse)
async def graph_expand(
    request: Request,
    entity_id: int,
    workspace_id: str = Query(..., description="Workspace ID"),
    depth: int = Query(2, ge=1, le=3, description="Traversal depth"),
    limit: int = Query(50, ge=1, le=500, description="Max neighbor nodes"),
) -> GraphResponse:
    """Expand a single entity by Neo4j internal ID — return its neighbors and edges."""
    from metatron.storage.graph_ops import get_graph_expand

    user_groups = await _resolve_user_groups(request, workspace_id)

    try:
        data = await asyncio.to_thread(
            get_graph_expand,
            entity_id,
            workspace_id,
            depth,
            limit,
            user_groups=user_groups,
        )
    except (ServiceUnavailable, SessionExpired, ConnectionError, BrokenPipeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Graph database unavailable: {exc}")
    except Exception as exc:
        logger.error(
            "api.graph.expand.error",
            entity_id=entity_id,
            workspace_id=workspace_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Graph query failed: {exc}")

    return GraphResponse(
        nodes=[GraphNode(**n) for n in data["nodes"]],
        edges=[GraphEdge(**e) for e in data["edges"]],
        truncated=data["truncated"],
    )
