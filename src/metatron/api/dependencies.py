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
    from metatron.memory.health import MemoryHealthService
    from metatron.memory.service import MemoryService
    from metatron.memory.snapshot import MemorySnapshotService


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

    # Wire pg_store into search so graph-leg status post-filter works on the
    # REST path — parity with the MCP path (_memory_deps.py). MTRNIX-324.
    search = MemorySearchService(qdrant=qdrant_store, redis=redis_cache, pg_store=pg_store)

    # Wire freshness_store so review-queue REST endpoints work. MTRNIX-324.
    from metatron.storage.freshness_pg import FreshnessStore

    freshness_store = getattr(request.app.state, "memory_freshness_store", None)
    if freshness_store is None:
        # Engine is already initialised above — reuse it.
        engine = request.app.state.memory_pg_engine
        freshness_store = FreshnessStore(engine)
        request.app.state.memory_freshness_store = freshness_store

    plugin_manager = request.app.state.plugin_manager
    service = MemoryService(
        redis_cache=redis_cache,
        qdrant_store=qdrant_store,
        pg_store=pg_store,
        workspace_id=workspace_id,
        search=search,
        freshness_store=freshness_store,
        event_bus=plugin_manager.get_event_bus(),
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

    plugin_manager = request.app.state.plugin_manager
    repo = AgentPersistence(engine)
    service = AgentRegistryService(
        repo,
        workspace_id=workspace_id,
        event_bus=plugin_manager.get_event_bus(),
    )

    services[workspace_id] = service
    request.app.state.agent_registry_services = services
    return service


def get_memory_health_service(request: Request) -> MemoryHealthService:
    """Return (and lazily construct) a per-workspace :class:`MemoryHealthService`.

    Shares the PostgreSQL async engine / ``MemoryPostgresStore`` with
    :func:`get_memory_service` so a single connection pool serves both.
    Settings are read from ``app.state.settings``.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.memory.health import MemoryHealthService
    from metatron.storage.memory_postgres import MemoryPostgresStore

    settings: Settings = request.app.state.settings
    workspace_id = _resolve_workspace_id(request)

    services: dict[str, MemoryHealthService] = getattr(
        request.app.state,
        "memory_health_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

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

    health_service = MemoryHealthService(
        pg_store=pg_store,
        workspace_id=workspace_id,
        settings=settings,
    )

    services[workspace_id] = health_service
    request.app.state.memory_health_services = services
    return health_service


def get_memory_snapshot_service(request: Request) -> MemorySnapshotService:
    """Return (and lazily construct) a per-workspace :class:`MemorySnapshotService`.

    Shares the PostgreSQL async engine / ``MemoryPostgresStore`` with
    :func:`get_memory_service` so a single connection pool serves both. The
    Qdrant store is workspace-scoped (collection name embeds the workspace),
    so we construct it inline — same pattern as :func:`get_memory_service`.
    """
    from pathlib import Path

    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.memory.snapshot import MemorySnapshotService
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

    settings: Settings = request.app.state.settings
    workspace_id = _resolve_workspace_id(request)

    services: dict[str, MemorySnapshotService] = getattr(
        request.app.state,
        "memory_snapshot_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

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

    plugin_manager = request.app.state.plugin_manager
    snapshot_service = MemorySnapshotService(
        pg_store=pg_store,
        qdrant_store=qdrant_store,
        workspace_id=workspace_id,
        snapshot_dir=Path(settings.snapshot_dir),
        max_file_bytes=settings.snapshot_max_file_bytes,
        event_bus=plugin_manager.get_event_bus(),
    )

    services[workspace_id] = snapshot_service
    request.app.state.memory_snapshot_services = services
    return snapshot_service
