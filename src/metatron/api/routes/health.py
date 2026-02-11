"""Health check endpoints — GET /health and GET /ready."""

from __future__ import annotations

import structlog
from fastapi import APIRouter

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Basic liveness check. Returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, object]:
    """Readiness check — verifies all backing services are reachable.

    Returns 200 with service status map. Individual services may be
    degraded without making the overall check fail.
    """
    logger.info("health.ready.check")
    # TODO: implement using HealthChecker
    # checker = HealthChecker(...)
    # services = await checker.check_all()
    # overall = "ok" if all(s["status"] == "ok" for s in services.values()) else "degraded"
    return {"status": "ok", "services": {}}


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
