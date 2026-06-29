"""Shared FastAPI dependencies — DI for stores and services.

These Depends() functions provide access to initialized stores
and services. They pull instances from app.state (set during lifespan).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import (  # noqa: TC002 — FastAPI Depends parameters need runtime type
    HTTPException,
    Query,
    Request,
)

from metronix.core.config import Settings  # noqa: TC001 — runtime annotations in function bodies
from metronix.llm.telemetry import set_telemetry_context

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from metronix.agents.service import AgentRegistryService
    from metronix.knowledge.service import RawDocumentReadService
    from metronix.llm.telemetry import TelemetryContext
    from metronix.memory.health import MemoryHealthService
    from metronix.memory.service import MemoryService
    from metronix.memory.snapshot import MemorySnapshotService


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


# Workspace ids appear as Qdrant collection-name path components and as
# filesystem directories under the snapshot root, so the resolver rejects
# anything outside this charset before returning a value.
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def resolve_workspace_id(request: Request) -> str:
    """Resolve workspace_id from an optional ``?workspace_id`` query param,
    access-checked against the caller's JWT.

    Semantics:
    - Param absent or whitespace-only -> :func:`get_workspace_id` (auth-derived).
    - Param literally ``"*"`` -> ``HTTPException(400)``. ``"*"`` is a wildcard
      inside the JWT, never a valid request target; reject explicitly instead of
      silently downgrading to the auth default.
    - Param outside ``^[A-Za-z0-9_-]{1,64}$`` -> ``HTTPException(400)``. Keeps
      ``..`` / ``/`` / very long ids out of downstream filesystem and Qdrant
      paths (a traversal would otherwise be possible via the snapshot service).
    - Param present, caller token holds ``"*"`` or the param is in the caller's
      ``workspace_ids`` -> the requested workspace is returned.
    - Param present, caller's ``workspace_ids`` does not grant access (incl. the
      empty-list case) -> ``HTTPException(403)``. ``OptionalAuthMiddleware``
      normalises admin tokens with empty ``workspace_ids`` into ``["*"]`` so
      this branch only fires for genuinely-confined callers.

    The resolved value is memoised on ``request.state._workspace_id_cached``
    so repeat resolutions within a single request (router dep + service DI +
    in-handler) cannot disagree if a downstream middleware mutates the query
    string (TOCTOU).

    Reads only ``request.query_params`` and ``request.state.user`` — no
    WorkspaceManager lookup. A nonexistent (but well-formed and granted)
    workspace yields an empty result set downstream rather than a 404.
    """
    cached: str | None = getattr(request.state, "_workspace_id_cached", None)
    if cached is not None:
        return cached

    raw = request.query_params.get("workspace_id")
    requested = (raw or "").strip()

    if not requested:
        result = get_workspace_id(request)
        request.state._workspace_id_cached = result
        return result

    if requested == "*":
        raise HTTPException(
            status_code=400,
            detail=(
                "workspace_id='*' is not a valid target — omit the parameter to "
                "use the auth-derived default"
            ),
        )

    if not _WORKSPACE_ID_RE.match(requested):
        raise HTTPException(
            status_code=400,
            detail="workspace_id must match ^[A-Za-z0-9_-]{1,64}$",
        )

    user = getattr(request.state, "user", {}) or {}
    allowed_raw = user.get("workspace_ids", [])
    # Defensive: a plugin auth backend could theoretically return a bare string;
    # without this guard ``requested in allowed`` becomes a substring match
    # (e.g. "ws" in "ws-acme" -> True). Coerce non-lists to an empty list.
    allowed: list[str] = allowed_raw if isinstance(allowed_raw, list) else []

    if "*" in allowed or requested in allowed:
        request.state._workspace_id_cached = requested
        return requested

    raise HTTPException(status_code=403, detail=f"No access to workspace '{requested}'")


def workspace_scope(
    request: Request,
    workspace_id: str | None = Query(  # noqa: ARG001 — declared for OpenAPI; value read via request
        None,
        description="Target workspace (auth-checked; overrides the JWT-derived default)",
    ),
) -> str:
    """Router-level dependency for REST family B (agents / memory / knowledge /
    snapshots).

    Two jobs in one place so individual handlers stay clean:

    1. **Declares** ``?workspace_id`` as an optional query parameter — because it
       is attached to the router, FastAPI surfaces the param in the OpenAPI schema
       for *every* route under that router, so typed frontend clients can pass it.
    2. **Enforces** the JWT access check via :func:`resolve_workspace_id` — raises
       403 for a workspace the caller may not target. This runs even when a
       handler's service dependency is overridden in tests, so enforcement is
       uniform.

    The ``workspace_id`` parameter is intentionally unused in the body — the value
    is read from ``request.query_params`` by :func:`resolve_workspace_id`. Returns
    the resolved workspace id; service DI helpers re-resolve the same value.
    """
    return resolve_workspace_id(request)


def build_telemetry_context_cm(
    request: Request,
    *,
    source: str,
) -> AbstractContextManager[TelemetryContext]:
    """Build a TelemetryContext context-manager from the current request.

    Resolves workspace_id via :func:`get_workspace_id` (handles the ``*``
    admin case), pulls user_id from auth state, generates a fresh
    correlation_id. Returns the context-manager *unentered* — callers use
    ``with build_telemetry_context_cm(request, source="rest"): ...``.

    Centralising this here keeps chat / openai-compat / future routes from
    re-implementing the same five-line dance.

    WARNING — by design this function uses :func:`get_workspace_id`, **not**
    :func:`resolve_workspace_id`. Audit logs must reflect the JWT-derived
    workspace, not whatever a ``?workspace_id`` query param requested, otherwise
    telemetry and authorisation can diverge. If a future caller needs the
    actually-served workspace in the telemetry context, call
    ``resolve_workspace_id`` explicitly at the handler instead of changing this
    helper.
    """
    workspace_id = get_workspace_id(request)
    user = getattr(request.state, "user", {}) or {}
    user_id: str | None = user.get("id") or user.get("user_id")
    return set_telemetry_context(
        workspace_id=workspace_id,
        user_id=user_id,
        source=source,
        correlation_id=uuid4(),
    )


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

    from metronix.memory.search import MemorySearchService
    from metronix.memory.service import MemoryService
    from metronix.storage.memory_postgres import MemoryPostgresStore
    from metronix.storage.memory_qdrant import MemoryQdrantStore
    from metronix.storage.memory_redis import RedisSessionCache
    from metronix.storage.redis import RedisStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

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
    # REST path — parity with the MCP path (_memory_deps.py). PROJ-324.
    search = MemorySearchService(qdrant=qdrant_store, redis=redis_cache, pg_store=pg_store)

    # Wire freshness_store so review-queue REST endpoints work. PROJ-324.
    from metronix.storage.freshness_pg import FreshnessStore

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

    from metronix.agents.persistence import AgentPersistence
    from metronix.agents.service import AgentRegistryService

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

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

    from metronix.memory.health import MemoryHealthService
    from metronix.storage.memory_postgres import MemoryPostgresStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

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

    from metronix.memory.snapshot import MemorySnapshotService
    from metronix.storage.memory_postgres import MemoryPostgresStore
    from metronix.storage.memory_qdrant import MemoryQdrantStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

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


def get_raw_document_service(request: Request) -> RawDocumentReadService:
    """Return (and lazily construct) a per-workspace :class:`RawDocumentReadService`.

    Reuses ``app.state.postgres`` (the shared :class:`~metronix.storage.postgres.PostgresStore`
    initialised in the lifespan) so no new connection pool is created.  If the
    lifespan store is not yet available — e.g. in isolated test setups — a new
    ``PostgresStore`` is constructed from ``settings.postgres_dsn``.

    Cached per workspace on ``app.state.raw_document_services`` (same pattern
    as :func:`get_memory_health_service`).
    """
    from metronix.knowledge.service import RawDocumentReadService
    from metronix.storage.postgres import PostgresStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

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
