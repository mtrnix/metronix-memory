"""Graph enrichment — augment retrieval results with knowledge graph context.

After initial vector search, we look up entities mentioned in the top
results and fetch their graph neighbors from Memgraph. This adds
relationship context that pure vector similarity misses.
"""

from __future__ import annotations

import structlog

from metronix.core.interfaces import GraphStoreInterface
from metronix.core.models import Chunk

logger = structlog.get_logger()


async def enrich_with_graph(
    chunks: list[Chunk],
    graph_store: GraphStoreInterface,
    workspace_id: str,
    max_neighbors: int = 5,
) -> dict[str, list[dict[str, str]]]:
    """Look up graph neighbors for entities found in chunks.

    Extracts entity names from chunk metadata, queries the graph
    for each, and returns a mapping of chunk_id → neighbor info.

    Args:
        chunks: Retrieval result chunks (with metadata.entities if available).
        graph_store: Graph store for neighbor lookups.
        workspace_id: Workspace scope.
        max_neighbors: Max neighbors per entity to fetch.

    Returns:
        Dict mapping chunk_id → list of neighbor dicts.
    """
    logger.info(
        "graph_enrichment.started",
        workspace_id=workspace_id,
        chunk_count=len(chunks),
    )
    # TODO: implement graph enrichment
    # 1. Extract entity names from chunk metadata (chunk.metadata.get("entities"))
    # 2. For each unique entity: graph_store.query_neighbors(workspace_id, entity)
    # 3. Build chunk_id → neighbors mapping
    # 4. Score neighbors by relevance (count of connections)
    # 5. Return top max_neighbors per chunk
    raise NotImplementedError("Graph enrichment not yet implemented")
