"""Benchmarker API — POST /api/v1/query/trace.

Runs a query through the full retrieval pipeline and returns
a detailed 7-step trace with timing for each step.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

logger = structlog.get_logger()

router = APIRouter(tags=["benchmarker"])


class QueryTraceRequest(BaseModel):
    """Request body for a traced query."""

    model_config = ConfigDict(strict=True)

    workspace_id: str
    query: str
    top_k: int = 10


@router.post("/query/trace")
async def query_trace(body: QueryTraceRequest) -> dict[str, object]:
    """Run a query with full tracing and return step-by-step timing.

    Returns a trace object with 7 steps:
    1. embed_query
    2. dense_search
    3. sparse_search
    4. rrf_fusion
    5. graph_enrichment
    6. multi_factor_scoring
    7. context_assembly

    Each step includes: name, duration_ms, metadata.
    """
    logger.info(
        "api.benchmarker.trace",
        workspace_id=body.workspace_id,
        query=body.query,
    )
    # TODO: implement
    # 1. Create QueryTrace(workspace_id, query)
    # 2. Run retrieval pipeline with trace instrumentation
    # 3. Store trace in postgres
    # 4. Return trace.to_dict()
    raise HTTPException(status_code=501, detail="Not yet implemented")
