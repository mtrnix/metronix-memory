"""Health check endpoints — GET /health and GET /ready."""

from __future__ import annotations

import asyncio
import contextlib
import functools

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Liveness check.

    200 while the process is running, 503 when the startup migration failed
    (the app would otherwise serve traffic against a half-built schema, #539).
    ``migrations_ok`` is unset until the lifespan has run, which counts as ok.
    """
    if getattr(request.app.state, "migrations_ok", None) is False:
        return JSONResponse({"status": "error", "migrations": "failed"}, status_code=503)
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Synchronous probe helpers (run via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _check_qdrant() -> None:
    from metronix.storage.qdrant import get_hybrid_store

    store = get_hybrid_store()
    store.client.get_collections()


def _check_neo4j() -> None:
    from metronix.storage.neo4j_graph import get_graph_driver

    driver = get_graph_driver()
    with driver.session() as s:
        s.run("RETURN 1")


@functools.lru_cache(maxsize=1)
def _alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from metronix.storage.migrations import _find_alembic_ini

    return ScriptDirectory.from_config(Config(_find_alembic_ini())).get_current_head() or ""


@functools.lru_cache(maxsize=1)
def _sync_engine():  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine

    from metronix.core.config import get_settings

    return create_engine(get_settings().postgres_sync_dsn, pool_pre_ping=True, pool_size=1)


def _check_migrations() -> None:
    """Raise unless Postgres is reachable and its schema is at the Alembic head."""
    from sqlalchemy import text

    head = _alembic_head()
    with _sync_engine().connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if current != head:
        raise RuntimeError(f"schema at {current!r}, expected head {head!r}")


def _check_ollama(ollama_url: str, embed_model: str) -> None:
    r = httpx.get(f"{ollama_url}/api/tags", timeout=3)
    if r.status_code != 200:
        raise RuntimeError(f"status {r.status_code}")
    installed = {m.get("name") for m in r.json().get("models", [])}
    # Ollama lists untagged models as "<name>:latest".
    wanted = {embed_model, embed_model if ":" in embed_model else f"{embed_model}:latest"}
    if not installed & wanted:
        raise RuntimeError(f"embedding model {embed_model!r} is not installed")


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness check — probes Postgres migrations, Qdrant, Neo4j, and Ollama.

    Returns 200 if the schema is at the Alembic head, all services are
    reachable and the embedding model is installed; 503 otherwise.
    Error details go to logs only — the response shows "ok" or "error".
    """
    services: dict[str, str] = {}

    # Postgres schema at Alembic head (#539)
    try:
        await asyncio.to_thread(_check_migrations)
        services["migrations"] = "ok"
    except Exception as e:
        logger.warning("health.migrations.error", error=str(e))
        services["migrations"] = "error"

    # Qdrant
    try:
        await asyncio.to_thread(_check_qdrant)
        services["qdrant"] = "ok"
    except Exception as e:
        logger.warning("health.qdrant.error", error=str(e))
        services["qdrant"] = "error"

    # Neo4j
    try:
        await asyncio.to_thread(_check_neo4j)
        services["neo4j"] = "ok"
    except Exception as e:
        logger.warning("health.neo4j.error", error=str(e))
        services["neo4j"] = "error"

    # Ollama (embeddings)
    try:
        from metronix.core.config import get_settings

        settings = get_settings()
        ollama_url = settings.ollama_host.rstrip("/")
        await asyncio.to_thread(_check_ollama, ollama_url, settings.ollama_embed_model)
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
    from metronix.observability.metrics import get_metrics

    data = get_metrics()
    with contextlib.suppress(Exception):
        from metronix.llm.embeddings import get_embedding_cache_stats

        data["embedding_cache"] = get_embedding_cache_stats()
    return data


@router.post("/metrics/reset")
def metrics_reset() -> dict[str, str]:
    """Reset all metrics counters and caches."""
    from metronix.observability.metrics import reset_metrics

    reset_metrics()
    with contextlib.suppress(Exception):
        from metronix.llm.embeddings import clear_embedding_cache

        clear_embedding_cache()
    return {"status": "reset"}
