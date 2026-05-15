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
    from metatron.chat.persistence import ChatPersistence
    from metatron.knowledge.service import RawDocumentReadService
    from metatron.memory.health import MemoryHealthService
    from metatron.memory.service import MemoryService
    from metatron.memory.snapshot import MemorySnapshotService
    from metatron.storage.bootstrap_state import BootstrapStateStore
    from metatron.workspaces.manager import WorkspaceManager


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


def get_chat_persistence(request: Request) -> ChatPersistence:
    """Return (and lazily construct) a :class:`~metatron.chat.persistence.ChatPersistence`.

    Reuses ``app.state.memory_pg_engine`` if it has been initialised by another
    dependency (e.g. ``get_memory_service``). If not present yet, creates a new
    engine and stores it under both ``memory_pg_engine`` and ``chat_pg_engine``
    keys so any subsequent dependency can reuse it.

    The :class:`ChatPersistence` itself is stateless (no per-workspace cache
    needed), so we return the same singleton for all workspaces.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.chat.persistence import ChatPersistence

    cached: ChatPersistence | None = getattr(request.app.state, "chat_persistence", None)
    if cached is not None:
        return cached

    settings: Settings = request.app.state.settings

    engine = getattr(request.app.state, "memory_pg_engine", None)
    if engine is None:
        engine = getattr(request.app.state, "chat_pg_engine", None)
    if engine is None:
        engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        request.app.state.memory_pg_engine = engine
    request.app.state.chat_pg_engine = engine

    persistence = ChatPersistence(engine)
    request.app.state.chat_persistence = persistence
    return persistence


def get_raw_document_service(request: Request) -> RawDocumentReadService:
    """Return (and lazily construct) a per-workspace :class:`RawDocumentReadService`.

    Reuses ``app.state.postgres`` (the shared :class:`~metatron.storage.postgres.PostgresStore`
    initialised in the lifespan) so no new connection pool is created.  If the
    lifespan store is not yet available — e.g. in isolated test setups — a new
    ``PostgresStore`` is constructed from ``settings.postgres_dsn``.

    Cached per workspace on ``app.state.raw_document_services`` (same pattern
    as :func:`get_memory_health_service`).
    """
    from metatron.knowledge.service import RawDocumentReadService
    from metatron.storage.postgres import PostgresStore

    settings: Settings = request.app.state.settings
    workspace_id = _resolve_workspace_id(request)

    services: dict[str, RawDocumentReadService] = getattr(
        request.app.state,
        "raw_document_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    # Prefer the shared PostgresStore created in lifespan (app.state.postgres).
    # Fall back to constructing a new one from settings if the lifespan store is
    # not present (common in minimal test-app setups).
    pg_store: PostgresStore | None = getattr(request.app.state, "postgres", None)
    if pg_store is None:
        pg_store = PostgresStore(settings.postgres_dsn)
        request.app.state.postgres = pg_store

    service = RawDocumentReadService(pg_store, workspace_id=workspace_id)

    services[workspace_id] = service
    request.app.state.raw_document_services = services
    return service


def get_bootstrap_state_store(request: Request) -> BootstrapStateStore:
    """Return (and lazily construct) the :class:`BootstrapStateStore`.

    Reuses ``app.state.memory_pg_engine`` if initialised by another dependency.
    Stores the singleton on ``app.state.bootstrap_state_store``.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.storage.bootstrap_state import BootstrapStateStore

    cached: BootstrapStateStore | None = getattr(
        request.app.state, "bootstrap_state_store", None
    )
    if cached is not None:
        return cached

    settings: Settings = request.app.state.settings

    engine = getattr(request.app.state, "memory_pg_engine", None)
    if engine is None:
        engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        request.app.state.memory_pg_engine = engine

    store = BootstrapStateStore(engine)
    request.app.state.bootstrap_state_store = store
    return store


def get_workspace_manager_async(request: Request) -> WorkspaceManager:
    """Return the ASOC-wired :class:`~metatron.workspaces.manager.WorkspaceManager`.

    Singleton on ``app.state.workspace_manager_async``.  Raises 503 if the
    lifespan wiring has not run.
    """
    from fastapi import HTTPException

    mgr: WorkspaceManager | None = getattr(
        request.app.state, "workspace_manager_async", None
    )
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="ASOC workspace manager not initialized.",
        )
    return mgr
