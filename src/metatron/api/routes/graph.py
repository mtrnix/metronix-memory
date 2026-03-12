"""Knowledge graph visualization API — /api/v1/graph."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from neo4j.exceptions import ServiceUnavailable, SessionExpired
from pydantic import BaseModel

router = APIRouter(prefix="/graph", tags=["graph"])


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
    workspace_id: str = Query(..., description="Workspace ID"),
    limit: int = Query(100, ge=1, le=500, description="Max nodes to return"),
) -> GraphResponse:
    """Get top-N most connected entities for initial graph render."""
    from metatron.storage.graph_ops import get_graph_overview

    try:
        data = await asyncio.to_thread(get_graph_overview, workspace_id, limit)
    except (ServiceUnavailable, SessionExpired, ConnectionError,
            BrokenPipeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Memgraph unavailable: {exc}")

    return GraphResponse(
        nodes=[GraphNode(**n) for n in data["nodes"]],
        edges=[GraphEdge(**e) for e in data["edges"]],
        truncated=data["truncated"],
    )


@router.get("/expand/{entity_id}", response_model=GraphResponse)
async def graph_expand(
    entity_id: int,
    workspace_id: str = Query(..., description="Workspace ID"),
    depth: int = Query(2, ge=1, le=3, description="Traversal depth"),
    limit: int = Query(50, ge=1, le=500, description="Max neighbor nodes"),
) -> GraphResponse:
    """Expand a single entity by Memgraph internal ID — return its neighbors and edges."""
    from metatron.storage.graph_ops import get_graph_expand

    try:
        data = await asyncio.to_thread(
            get_graph_expand, entity_id, workspace_id, depth, limit,
        )
    except (ServiceUnavailable, SessionExpired, ConnectionError,
            BrokenPipeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Memgraph unavailable: {exc}")

    return GraphResponse(
        nodes=[GraphNode(**n) for n in data["nodes"]],
        edges=[GraphEdge(**e) for e in data["edges"]],
        truncated=data["truncated"],
    )
