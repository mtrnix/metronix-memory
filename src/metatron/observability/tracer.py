"""Query trace — step-by-step timing for the 7-step retrieval pipeline.

Records each step's name, duration, and metadata. Used by the
benchmarker API to return full query traces.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator
from uuid import uuid4

import structlog

from metatron.core.models import QueryStep

logger = structlog.get_logger()


class QueryTrace:
    """Records timing and metadata for each step of a query pipeline.

    Usage:
        trace = QueryTrace(workspace_id="ws_123")
        with trace.step("embed_query") as s:
            embedding = await llm.embed([query])
            s["vector_dim"] = len(embedding[0])
        with trace.step("dense_search") as s:
            results = await vector_store.search_dense(...)
            s["result_count"] = len(results)
        trace_dict = trace.to_dict()

    The 7 standard steps:
    1. embed_query — generate query embedding
    2. dense_search — ANN vector search
    3. sparse_search — BM25 keyword search
    4. rrf_fusion — merge ranked lists
    5. graph_enrichment — knowledge graph lookups
    6. multi_factor_scoring — re-rank with 6 signals
    7. context_assembly — build final context for LLM
    """

    def __init__(self, workspace_id: str = "", query: str = "") -> None:
        self.id: str = uuid4().hex
        self.workspace_id: str = workspace_id
        self.query: str = query
        self.steps: list[QueryStep] = []
        self._start_time: float = time.monotonic()

    @contextmanager
    def step(self, name: str) -> Generator[dict[str, str | int | float], None, None]:
        """Context manager that times a pipeline step.

        Args:
            name: Step name (e.g., "embed_query", "dense_search").

        Yields:
            Mutable metadata dict — add key-value pairs for logging.
        """
        metadata: dict[str, str | int | float] = {}
        start = time.monotonic()
        try:
            yield metadata
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            step = QueryStep(
                name=name,
                duration_ms=round(duration_ms, 2),
                metadata=metadata,
            )
            self.steps.append(step)
            logger.info(
                "trace.step.completed",
                trace_id=self.id,
                step=name,
                duration_ms=step.duration_ms,
                **{k: v for k, v in metadata.items() if isinstance(v, (str, int, float))},
            )

    def to_dict(self) -> dict[str, object]:
        """Serialize the full trace for storage and API response.

        Returns:
            Dict with trace_id, workspace_id, query, total_ms, and steps.
        """
        total_ms = round((time.monotonic() - self._start_time) * 1000, 2)
        return {
            "trace_id": self.id,
            "workspace_id": self.workspace_id,
            "query": self.query,
            "total_ms": total_ms,
            "steps": [
                {
                    "name": s.name,
                    "duration_ms": s.duration_ms,
                    "metadata": s.metadata,
                }
                for s in self.steps
            ],
        }
