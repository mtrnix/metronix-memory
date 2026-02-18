"""Health check endpoints — GET /health and GET /ready."""

from __future__ import annotations

import asyncio

import httpx
import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Basic liveness check. Returns 200 if the process is running."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Synchronous probe helpers (run via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _check_qdrant() -> None:
    from metatron.storage.qdrant import get_hybrid_store
    store = get_hybrid_store()
    store.client.get_collections()


def _check_memgraph() -> None:
    from metatron.storage.memgraph import get_memgraph_driver
    driver = get_memgraph_driver()
    with driver.session() as s:
        s.run("RETURN 1")


def _check_ollama(ollama_url: str) -> None:
    r = httpx.get(f"{ollama_url}/api/tags", timeout=3)
    if r.status_code != 200:
        raise RuntimeError(f"status {r.status_code}")


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness check — probes Qdrant, Memgraph, and Ollama.

    Returns 200 if all services are reachable, 503 if any are degraded.
    Error details go to logs only — the response shows "ok" or "error".
    """
    services: dict[str, str] = {}

    # Qdrant
    try:
        await asyncio.to_thread(_check_qdrant)
        services["qdrant"] = "ok"
    except Exception as e:
        logger.warning("health.qdrant.error", error=str(e))
        services["qdrant"] = "error"

    # Memgraph
    try:
        await asyncio.to_thread(_check_memgraph)
        services["memgraph"] = "ok"
    except Exception as e:
        logger.warning("health.memgraph.error", error=str(e))
        services["memgraph"] = "error"

    # Ollama (embeddings)
    try:
        from metatron.core.config import get_settings
        ollama_url = get_settings().ollama_host.rstrip("/")
        await asyncio.to_thread(_check_ollama, ollama_url)
        services["ollama"] = "ok"
    except Exception as e:
        logger.warning("health.ollama.error", error=str(e))
        services["ollama"] = "error"

    all_ok = all(v == "ok" for v in services.values())
    return JSONResponse(
        content={"status": "ready" if all_ok else "degraded", "services": services},
        status_code=200 if all_ok else 503,
    )


@router.get("/metrics")
def metrics() -> dict[str, object]:
    """Get application metrics (timing stats, request counters, cache stats)."""
    from metatron.observability.metrics import get_metrics
    data = get_metrics()
    try:
        from metatron.llm.embeddings import get_embedding_cache_stats
        data["embedding_cache"] = get_embedding_cache_stats()
    except Exception:
        pass
    return data


@router.post("/metrics/reset")
def metrics_reset() -> dict[str, str]:
    """Reset all metrics counters and caches."""
    from metatron.observability.metrics import reset_metrics
    reset_metrics()
    try:
        from metatron.llm.embeddings import clear_embedding_cache
        clear_embedding_cache()
    except Exception:
        pass
    return {"status": "reset"}
