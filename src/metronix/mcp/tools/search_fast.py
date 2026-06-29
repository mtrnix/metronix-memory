"""MCP tool: metronix_search_fast — low-latency dense+metadata retrieval."""

from __future__ import annotations

import time
from typing import Any

import structlog

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools.models import SearchFastItem, SearchFastResponse

logger = structlog.get_logger(__name__)


def _hit_to_item(hit: dict[str, Any]) -> SearchFastItem:
    """Project a Qdrant hit dict onto the MCP SearchFastItem schema."""
    payload = hit.get("payload") or {}

    def pick(key: str, default: str = "") -> str:
        value = hit.get(key)
        if value is None or value == "":
            value = payload.get(key, default)
        return str(value) if value is not None else default

    content = hit.get("memory") or hit.get("data") or payload.get("memory") or payload.get("data")
    return SearchFastItem(
        doc_label=pick("doc_label"),
        title=pick("title"),
        content=str(content or ""),
        source_type=pick("source_type") or pick("type"),
        score=float(hit.get("score") or payload.get("score") or 0.0),
        url=pick("url"),
        date=pick("date"),
    )


@mcp.tool(
    description=(
        "Fast knowledge-base lookup (dense + optional metadata recall).\n\n"
        "**When to use:** routine lookups where you need raw passages fast "
        "and do NOT need a synthesized answer. Skips reranker / HyDE / "
        "graph / LLM stages. Target P50 <800 ms.\n\n"
        "**Parameters:**\n"
        "- query: Natural language query or keyword (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- top_k: Results to return (1..50, default 10)\n\n"
        "**Returns:** raw passages with title/content/source/score — no answer."
    ),
)
async def metronix_search_fast(
    query: str,
    workspace_id: str | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """Fast dense+metadata retrieval (no rerank, no answer)."""
    try:
        if not query or not query.strip():
            raise ValueError("query is required")

        from metronix.retrieval.search import fast_search

        top_k = min(max(1, int(top_k)), 50)
        from metronix.mcp.config import resolve_workspace_id

        ws_id = resolve_workspace_id(workspace_id)

        start = time.perf_counter()
        hits = await fast_search(query, workspace_id=ws_id, top_k=top_k)
        latency_ms = int((time.perf_counter() - start) * 1000)

        items = [_hit_to_item(h) for h in hits]
        logger.info(
            "metronix_search_fast.done",
            workspace_id=ws_id,
            count=len(items),
            latency_ms=latency_ms,
        )
        return SearchFastResponse(
            results=items,
            count=len(items),
            latency_ms=latency_ms,
        ).model_dump()

    except Exception as exc:  # noqa: BLE001 — converted to MCPError
        error = handle_tool_error("metronix_search_fast", exc)
        return {"error": error.to_dict()}
