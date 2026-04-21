"""Shared FastAPI dependencies — DI for stores and services.

These Depends() functions provide access to initialized stores
and services. They pull instances from app.state (set during lifespan).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request  # noqa: TC002 — FastAPI Depends parameters need runtime type

from metatron.core.config import Settings  # noqa: TC001 — runtime annotations in function bodies

if TYPE_CHECKING:
    from metatron.agents.service import AgentRegistryService
    from metatron.memory.service import MemoryService


async def get_settings(request: Request) -> Settings:
    """Get application settings from app state."""
    return request.app.state.settings


async def get_postgres(request: Request):  # type: ignore[no-untyped-def]
    """Get PostgresStore from app state.

    Returns:
        PostgresStore instance.
    """
    # TODO: implement once stores are initialized in lifespan
    # return request.app.state.postgres
    raise NotImplementedError("PostgresStore not initialized")


async def get_vector_store(request: Request):  # type: ignore[no-untyped-def]
    """Get QdrantVectorStore from app state."""
    # TODO: implement
    # return request.app.state.qdrant
    raise NotImplementedError("VectorStore not initialized")


async def get_graph_store(request: Request):  # type: ignore[no-untyped-def]
    """Get Neo4j GraphStore from app state."""
    # TODO: implement
    # return request.app.state.neo4j
    raise NotImplementedError("GraphStore not initialized")


async def get_llm_provider(request: Request):  # type: ignore[no-untyped-def]
    """Get LLM provider from app state."""
    # TODO: implement
    # return request.app.state.ollama
    raise NotImplementedError("LLMProvider not initialized")


def get_workspace_id(request: Request) -> str:
    """Resolve workspace_id from auth state or settings default.

    Never reads from query or body — workspace comes from the authenticated
    user. Route handlers should import this helper rather than re-implementing
    the fallback chain locally.
    """
    user = getattr(request.state, "user", {}) or {}
    workspace_ids = user.get("workspace_ids", [])
    if workspace_ids and workspace_ids[0] != "*":
        return str(workspace_ids[0])
    settings: Settings = request.app.state.settings
    return settings.default_workspace_id


# Backwards-compatible alias — older callers use the private name.
_resolve_workspace_id = get_workspace_id


def get_memory_service(request: Request) -> MemoryService:
    """Return (and lazily construct) a per-workspace MemoryService.

    PostgreSQL engine, Redis cache and memory PG store are shared across
    workspaces on ``app.state``. Qdrant store and search service are per
    workspace because the Qdrant collection name is workspace-scoped.

    TODO: wire disposal of ``memory_pg_engine``, ``redis_cache`` and cached
    ``MemoryQdrantStore`` clients into the app lifespan shutdown handler —
    these connections currently outlive request scope but are never closed.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.memory.search import MemorySearchService
    from metatron.memory.service import MemoryService
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore
    from metatron.storage.memory_redis import RedisSessionCache
    from metatron.storage.redis import RedisStore

    settings: Settings = request.app.state.settings
    workspace_id = _resolve_workspace_id(request)

    services: dict[str, MemoryService] = getattr(
        request.app.state,
        "memory_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    redis_cache: RedisSessionCache | None = getattr(
        request.app.state,
        "redis_cache",
        None,
    )
    if redis_cache is None:
        redis_store = RedisStore(settings.redis_url)
        redis_cache = RedisSessionCache(
            redis_store,
            default_ttl=settings.memory_session_ttl,
        )
        request.app.state.redis_cache = redis_cache

    pg_store: MemoryPostgresStore | None = getattr(
        request.app.state,
        "memory_pg_store",
        None,
    )
    if pg_store is None:
        engine = getattr(request.app.state, "memory_pg_engine", None)
        if engine is None:
            engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
            request.app.state.memory_pg_engine = engine
        pg_store = MemoryPostgresStore(engine)
        request.app.state.memory_pg_store = pg_store

    qdrant_store = MemoryQdrantStore(
        workspace_id=workspace_id,
        host=settings.qdrant_host,
        port=settings.qdrant_http_port,
    )
    search = MemorySearchService(qdrant=qdrant_store, redis=redis_cache)

    service = MemoryService(
        redis_cache=redis_cache,
        qdrant_store=qdrant_store,
        pg_store=pg_store,
        workspace_id=workspace_id,
        search=search,
    )

    services[workspace_id] = service
    request.app.state.memory_services = services
    return service


def get_agent_registry_service(request: Request) -> AgentRegistryService:
    """Return (and lazily construct) a per-workspace :class:`AgentRegistryService`.

    Shares the PostgreSQL async engine with :func:`get_memory_service` under
    ``app.state.memory_pg_engine``. If neither dependency has run yet, the
    engine is created here and stored under both keys so the first caller
    wins and subsequent callers reuse it.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.agents.persistence import AgentPersistence
    from metatron.agents.service import AgentRegistryService

    settings: Settings = request.app.state.settings
    workspace_id = _resolve_workspace_id(request)

    services: dict[str, AgentRegistryService] = getattr(
        request.app.state,
        "agent_registry_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    engine = getattr(request.app.state, "memory_pg_engine", None)
    if engine is None:
        engine = getattr(request.app.state, "agents_pg_engine", None)
    if engine is None:
        engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        request.app.state.memory_pg_engine = engine
    request.app.state.agents_pg_engine = engine

    repo = AgentPersistence(engine)
    service = AgentRegistryService(repo, workspace_id=workspace_id)

    services[workspace_id] = service
    request.app.state.agent_registry_services = services
    return service
