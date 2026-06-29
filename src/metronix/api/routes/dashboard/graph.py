"""Dashboard knowledge graph endpoints."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from metronix.workspaces.models import Workspace

from .overview import get_valid_workspace

router = APIRouter()


class OrphanNode(BaseModel):
    """Orphan node details."""

    id: str
    label: str
    name: str


class GraphLineage(BaseModel):
    """Data lineage statistics."""

    raw_documents: int
    chunks: int
    graph_nodes: int


class GraphStatsResponse(BaseModel):
    """Knowledge graph statistics response."""

    total_nodes: int
    total_edges: int
    orphan_nodes: int
    orphan_list: list[OrphanNode]
    lineage: GraphLineage


@router.get("/graph-stats", response_model=GraphStatsResponse)
async def get_graph_stats(
    workspace: Annotated[Workspace, Depends(get_valid_workspace)],
) -> GraphStatsResponse:
    """Get knowledge graph statistics for dashboard.

    Args:
        workspace: Validated workspace from dependency.

    Returns:
        Graph statistics including nodes, edges, orphans, and lineage.
    """
    from metronix.storage.dashboard_queries import get_graph_stats_data

    stats = await asyncio.to_thread(get_graph_stats_data, workspace.workspace_id)

    return GraphStatsResponse(
        total_nodes=stats["total_nodes"],
        total_edges=stats["total_edges"],
        orphan_nodes=stats["orphan_nodes"],
        orphan_list=[
            OrphanNode(id=o["id"], label=o["label"], name=o["name"]) for o in stats["orphan_list"]
        ],
        lineage=GraphLineage(
            raw_documents=stats["raw_documents"],
            chunks=stats["chunks"],
            graph_nodes=stats["total_nodes"],
        ),
    )
