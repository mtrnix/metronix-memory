"""FastAPI application factory.

Creates and configures the FastAPI app with all routers,
middleware, and lifespan events. Uses the factory pattern
so tests can create isolated app instances.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from metatron.api.middleware import OptionalAuthMiddleware
from metatron.api.routes import (
    admin,
    agents,
    auth,
    benchmarker,
    chat,
    config,
    connections,
    dashboard,
    documents,
    files,
    graph,
    health,
    knowledge,
    memory,
    skills,
    snapshots,
    sync,
    users,
    workspaces,
)
from metatron.core.config import Settings
from metatron.core.logging import configure_logging
from metatron.core.plugin import PluginManager, discover_plugins

logger = structlog.get_logger()


# MCP server instance — imported to register tools
import metatron.mcp.tools  # noqa: F401 — registers @mcp.tool() decorators
from metatron.mcp.server import mcp as mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown logic.

    Startup: configure logging, initialize stores, register connectors.
    Shutdown: close all connections gracefully.
    """
    settings: Settings = app.state.settings
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )
    logger.info("app.startup", env=settings.env, port=settings.port)
    logger.info(
        "app.feature_flags",
        splade_enabled=settings.splade_enabled,
        hyde_enabled=settings.hyde_enabled,
        adaptive_rrf_enabled=settings.adaptive_rrf_enabled,
        hierarchical_chunking_enabled=settings.hierarchical_chunking_enabled,
        reranker_enabled=settings.reranker_enabled,
        graph_extraction_enabled=settings.graph_extraction_enabled,
    )

    # Apply pending database migrations before serving traffic.
    # Advisory lock ensures only one replica runs migrations when several
    # instances start simultaneously. Failures are non-fatal — the app
    # continues if the schema is already up to date.
    try:
        import asyncio

        from metatron.storage.migrations import run_migrations_sync

        await asyncio.to_thread(
            run_migrations_sync, settings.postgres_sync_dsn, settings.postgres_dsn
        )
    except Exception as exc:
        logger.error("migrations.failed", error=str(exc))

    # Ensure Memgraph property indexes exist (idempotent, non-fatal)
    try:
        import asyncio as _asyncio

        from metatron.storage.neo4j_graph import ensure_graph_indexes

        await _asyncio.to_thread(ensure_graph_indexes)
    except Exception as exc:
        logger.warning("neo4j.indexes.failed", error=str(exc))

    # One-time migration: env-var credentials → DB connections (idempotent)
    try:
        from metatron.storage.migrate_env_connections import migrate_env_to_db

        mig = await migrate_env_to_db(
            postgres_dsn=settings.postgres_dsn,
            workspace_id=settings.default_workspace_id,
            fernet_key=settings.fernet_key,
        )
        if mig["created"]:
            logger.info("env_migration.done", created=mig["created"])
    except Exception as exc:
        logger.warning("env_migration.failed", error=str(exc))

    # Recover from any syncs interrupted by a previous shutdown.
    # Reset `sync_logs.running` → `failed` and `connections.syncing` → `error`.
    try:
        import asyncio as _asyncio

        from metatron.storage.recovery import recover_interrupted_syncs

        rec = await _asyncio.to_thread(recover_interrupted_syncs)
        if rec["sync_logs_reset"] or rec["connections_reset"]:
            logger.info(
                "sync.recovery.applied",
                sync_logs_reset=rec["sync_logs_reset"],
                connections_reset=rec["connections_reset"],
            )
    except Exception as exc:
        logger.warning("sync.recovery.startup_failed", error=str(exc))

    # --- Shared DB engine for user store + API key store ---
    _user_engine = None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine as _create_engine

        _user_engine = _create_engine(settings.postgres_dsn)
    except Exception as exc:
        logger.error("db_engine.init.failed", error=str(exc))

    # --- User store ---
    try:
        if _user_engine is None:
            raise RuntimeError("DB engine not initialized")
        from metatron.auth.user_store import UserStore

        user_store = UserStore(_user_engine)
        logger.info("user_store.init.starting")
        await user_store.ensure_schema()
        logger.info("user_store.schema.done")
        seeded = await user_store.seed_admin(settings.auth_password)
        if seeded:
            logger.info("user_store.admin.seeded", email="admin@metatron.local")
        app.state.user_store = user_store
        logger.info("user_store.ready")
    except Exception as exc:
        import traceback

        logger.error("user_store.init.failed", error=str(exc))
        traceback.print_exc()

    # --- Platform user mapper ---
    try:
        if _user_engine is None:
            raise RuntimeError("DB engine not initialized")
        from metatron.auth.user_mapping import PlatformUserMapper

        platform_mapper = PlatformUserMapper(_user_engine, user_store)
        await platform_mapper.ensure_schema()
        app.state.platform_mapper = platform_mapper
        logger.info("platform_mapper.ready")
    except Exception as exc:
        logger.warning("platform_mapper.init.failed", error=str(exc))

    # --- API Key store (personal keys for /v1 endpoints) ---
    try:
        if _user_engine is None:
            raise RuntimeError("DB engine not initialized")
        from metatron.auth.api_key_store import ApiKeyStore

        api_key_store = ApiKeyStore(_user_engine)
        await api_key_store.ensure_schema()
        app.state.api_key_store = api_key_store
        logger.info("api_key_store.ready")
    except Exception as exc:
        logger.error("api_key_store.init.failed", error=str(exc))

    # --- Open WebUI sync (bundled scenario) ---
    if settings.openwebui_url:
        try:
            from metatron.auth.openwebui_sync import OpenWebUISync

            owui_sync = OpenWebUISync(
                owui_url=settings.openwebui_url,
                metatron_url=settings.openwebui_metatron_url,
                admin_email="admin@metatron.local",
                admin_password=settings.auth_password,
            )
            await owui_sync.ensure_admin()
            app.state.owui_sync = owui_sync
            logger.info("owui_sync.configured", url=settings.openwebui_url)
        except Exception as exc:
            logger.warning("owui_sync.init.failed", error=str(exc))

    # --- PostgresStore (shared) ---
    from metatron.storage.postgres import PostgresStore

    store = PostgresStore(settings.postgres_dsn)
    app.state.postgres = store

    # --- Channel manager (starts bots from DB config) ---
    if not getattr(app.state, "channel_manager", None):
        try:
            from metatron.agent.router import AgentRouter
            from metatron.channels.manager import ChannelManager

            agent_router = AgentRouter(settings=settings)
            channel_manager = ChannelManager(router=agent_router, store=store)
            started = await channel_manager.start_channels_from_db(
                fernet_key=settings.fernet_key,
                default_workspace_id=settings.default_workspace_id,
            )
            app.state.channel_manager = channel_manager
            logger.info("channel_manager.started", channels=started)
        except Exception as exc:
            logger.warning("channel_manager.startup_failed", error=str(exc))

    # Initialize MCP session manager (required for streamable-http transport)
    async with mcp_server.session_manager.run():
        logger.info("mcp.session_manager.started")

        # --- Proxy LLM client (MTRNIX-372) ---
        from metatron.proxy.upstream import UpstreamLLMClient

        app.state.upstream_llm_client = UpstreamLLMClient(
            timeout=settings.proxy_upstream_timeout_ms / 1000
        )

        yield

    # Shutdown
    logger.info("app.shutdown")
    cm = getattr(app.state, "channel_manager", None)
    if cm is not None:
        await cm.stop_all()
    owui_sync = getattr(app.state, "owui_sync", None)
    if owui_sync and owui_sync._client:
        await owui_sync._client.close()
    upstream_client = getattr(app.state, "upstream_llm_client", None)
    if upstream_client is not None:
        await upstream_client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured FastAPI application.

    Args:
        settings: App settings. If None, loaded from environment.

    Returns:
        Configured FastAPI instance.
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="Metatron Core",
        description="AI knowledge agent for teams",
        version="0.1.0",
        lifespan=lifespan,
        redirect_slashes=False,
    )
    app.state.settings = settings

    # --- Plugin discovery (must happen before middleware/routes) ---
    plugin_manager = PluginManager()
    discover_plugins(plugin_manager)
    app.state.plugin_manager = plugin_manager

    # --- Subscribe core event handlers ---
    from metatron.core.events import SYNC_COMPLETED
    from metatron.retrieval.channels import on_sync_completed

    plugin_manager.get_event_bus().subscribe(SYNC_COMPLETED, on_sync_completed)

    # --- Subscribe activity logger (WS4 S6) ---
    if settings.activity_log_enabled:
        from sqlalchemy.ext.asyncio import create_async_engine

        from metatron.activity.logger import ActivityLogger
        from metatron.storage.activity_pg import ActivityStore

        # Reuse/initialize the shared PG engine stored on app.state (also used by
        # memory/ and agents/ dependencies). Create on demand if no earlier
        # dependency has run yet.
        engine = getattr(app.state, "memory_pg_engine", None)
        if engine is None:
            engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
            app.state.memory_pg_engine = engine

        activity_store = ActivityStore(engine)
        activity_logger_instance = ActivityLogger(store=activity_store)
        activity_logger_instance.subscribe(plugin_manager.get_event_bus())
        app.state.activity_store = activity_store
        app.state.activity_logger = activity_logger_instance
        logger.info("activity_logger.subscribed")

        # Point the MCP tool wrapper at this bus (WS4 S6).
        from metatron.mcp import server as _mcp_mod

        _mcp_mod.set_activity_bus_getter(lambda: plugin_manager.get_event_bus())

    # Enterprise plugin requires auth — auto-enable if any plugin loaded
    if plugin_manager.loaded_plugins and not settings.auth_enabled:
        settings = settings.model_copy(update={"auth_enabled": True})
        app.state.settings = settings
        logger.info("auth.auto_enabled", reason="enterprise plugin loaded")

    # CORS — credentials are only safe with explicit origins, not wildcard
    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Plugin middlewares — added before OptionalAuth so they become inner layers.
    # Starlette prepends each add_middleware call, so the last-added runs first.
    # Order: OptionalAuthMiddleware (outermost) → plugin middlewares → CORS → routes.
    # This ensures core JWT auth always sets request.state.user before RBAC checks it.
    for middleware_class, kwargs in plugin_manager.get_middlewares():
        app.add_middleware(middleware_class, **kwargs)
        logger.info("plugin.middleware.applied", middleware=middleware_class.__name__)

    # Auth middleware — added last, becomes outermost, runs first on every request
    app.add_middleware(OptionalAuthMiddleware)

    from metatron.api.middleware.agent_id import AgentIdContextMiddleware

    app.add_middleware(AgentIdContextMiddleware)

    # Register core route modules
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(connections.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")
    app.include_router(benchmarker.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(graph.router, prefix="/api/v1")
    app.include_router(config.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(memory.router, prefix="/api/v1")
    app.include_router(knowledge.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(snapshots.router, prefix="/api/v1")

    from metatron.api.routes.finops import router as finops_router

    app.include_router(finops_router, prefix="/api/v1")

    from metatron.api.routes.openwebui_import import router as owui_import_router

    app.include_router(owui_import_router, prefix="/api/v1")

    # OpenAI-compatible API (for Open WebUI integration)
    if settings.openai_compat_enabled:
        from metatron.api.routes.openai_compat import router as openai_compat_router

        app.include_router(openai_compat_router)

    # --- Proxy LLM service builder (MTRNIX-372) ---
    if settings.proxy_enabled:
        from metatron.agents.persistence import AgentPersistence
        from metatron.agents.service import AgentRegistryService
        from metatron.api.routes.openai_compat import build_rag_stream
        from metatron.api.routes.proxy import router as proxy_router
        from metatron.core.events import ENTITY_WRITE
        from metatron.memory.assembler import AgentContextAssembler
        from metatron.memory.search import MemorySearchService
        from metatron.memory.service import MemoryService
        from metatron.proxy.activity import ProxyActivityLogger
        from metatron.proxy.credentials import UpstreamCredentialsResolver
        from metatron.proxy.entity_trie import WorkspaceEntityTrie
        from metatron.proxy.service import ProxyService
        from metatron.proxy.tool_result import ToolResultEnricher
        from metatron.storage.llm_upstream_credentials import LlmUpstreamCredentialsStore
        from metatron.storage.memory_postgres import MemoryPostgresStore
        from metatron.storage.memory_qdrant import MemoryQdrantStore
        from metatron.storage.memory_redis import RedisSessionCache
        from metatron.storage.redis import RedisStore

        bus = plugin_manager.get_event_bus()

        # Lazily-built per-workspace entity trie for tool-result enrichment.
        async def _fetch_entities(workspace_id: str) -> list[str]:
            import asyncio as _asyncio

            def _query() -> list[str]:
                from metatron.storage.neo4j_graph import get_graph_driver

                driver = get_graph_driver()
                cap = settings.proxy_entity_trie_max_entities_per_ws
                with driver.session() as session:
                    result = session.run(
                        "MATCH (e:Entity {workspace_id: $ws}) "
                        "RETURN e.name AS name LIMIT $cap",
                        {"ws": workspace_id, "cap": cap},
                    )
                    return [row["name"] for row in result if row["name"]]

            try:
                return await _asyncio.to_thread(_query)
            except Exception:  # noqa: BLE001 — empty trie on graph failure
                return []

        entity_trie = WorkspaceEntityTrie(settings=settings, fetch_entities=_fetch_entities)
        app.state.entity_trie = entity_trie

        async def _on_entity_write(event_name: str, payload: dict[str, object]) -> None:
            ws = payload.get("workspace_id")
            if ws:
                entity_trie.invalidate(str(ws))

        bus.subscribe(ENTITY_WRITE, _on_entity_write)

        async def _fetch_entity_memories(
            ws: str, entity: str, agent: str
        ) -> list[dict[str, object]]:
            import asyncio as _asyncio

            from metatron.storage.memory_graph import get_memories_about_entity

            nodes = await _asyncio.to_thread(get_memories_about_entity, ws, entity, 3, agent)
            # The Neo4j MemoryRecord node intentionally stores NO content
            # ("content lives in Qdrant"). Resolve it from PG (source of truth)
            # so the enricher has text to append (MTRNIX-372 review — P4 content).
            pg_store = getattr(app.state, "memory_pg_store", None)
            if pg_store is None:
                return nodes
            enriched: list[dict[str, object]] = []
            for node in nodes:
                rid = node.get("id")
                if not rid:
                    continue
                record = await pg_store.get(ws, str(rid))
                if record is not None:
                    enriched.append({**node, "content": record.content})
            return enriched

        def _proxy_service_builder(workspace_id: str) -> ProxyService:
            engine = getattr(app.state, "memory_pg_engine", None)
            if engine is None:
                from sqlalchemy.ext.asyncio import create_async_engine

                engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
                app.state.memory_pg_engine = engine

            pg_store = getattr(app.state, "memory_pg_store", None)
            if pg_store is None:
                pg_store = MemoryPostgresStore(engine)
                app.state.memory_pg_store = pg_store

            redis_cache = getattr(app.state, "redis_cache", None)
            if redis_cache is None:
                redis_cache = RedisSessionCache(
                    RedisStore(settings.redis_url),
                    default_ttl=settings.memory_session_ttl,
                )
                app.state.redis_cache = redis_cache

            qdrant_store = MemoryQdrantStore(
                workspace_id=workspace_id,
                host=settings.qdrant_host,
                port=settings.qdrant_http_port,
            )
            mem_search = MemorySearchService(
                qdrant=qdrant_store, redis=redis_cache, pg_store=pg_store,
            )
            mem_service = MemoryService(
                redis_cache=redis_cache, qdrant_store=qdrant_store,
                pg_store=pg_store, workspace_id=workspace_id,
                search=mem_search, event_bus=bus,
            )
            assembler = AgentContextAssembler(
                memory_service=mem_service, memory_search=mem_search, settings=settings,
            )
            agent_service = AgentRegistryService(
                AgentPersistence(engine), workspace_id=workspace_id, event_bus=bus,
            )
            creds_store = LlmUpstreamCredentialsStore(engine, fernet_key=settings.fernet_key)
            credentials = UpstreamCredentialsResolver(
                creds_store, default_key=settings.proxy_default_upstream_key,
            )
            activity_store = getattr(app.state, "activity_store", None)

            def _enricher_for(ws: str) -> ToolResultEnricher:
                return ToolResultEnricher(
                    trie=entity_trie,
                    fetch_memories=_fetch_entity_memories,
                    settings=settings,
                    activity_logger=ProxyActivityLogger(store=activity_store, workspace_id=ws),
                )

            return ProxyService(
                assembler=assembler,
                upstream_client=app.state.upstream_llm_client,
                credentials=credentials,
                agent_service=agent_service,
                event_bus=bus,
                settings=settings,
                activity_logger_factory=lambda ws: ProxyActivityLogger(
                    store=activity_store, workspace_id=ws,
                ),
                tool_result_enricher_factory=_enricher_for,
                rag_stream_factory=build_rag_stream,
            )

        app.state.proxy_service_builder = _proxy_service_builder

        app.include_router(proxy_router)

    # Lazy import benchmarker module router (optional dependency)
    try:
        from metatron.benchmarker.api import router as benchmarker_module_router

        app.include_router(benchmarker_module_router, prefix="/api/v1/benchmarker")
        logger.info("Benchmarker module loaded successfully")
    except ImportError as e:
        logger.warning(
            "Benchmarker module not available (missing optional dependencies): %s",
            e,
        )

    # Plugin routes — included after all core routes
    for router, prefix in plugin_manager.get_routes():
        app.include_router(router, prefix=prefix)
        logger.info("plugin.routes.applied", prefix=prefix or "(no prefix)")

    # Mount MCP server at /mcp
    # streamable_http_app() creates session_manager (initialized in lifespan).
    # We add the ASGI handler as a direct route — Starlette Mount breaks POST
    # without trailing slash (405), and methods=None confuses FastAPI.
    from starlette.routing import Route as StarletteRoute

    mcp_starlette_app = mcp_server.streamable_http_app()
    mcp_asgi_handler = mcp_starlette_app.routes[0].endpoint
    app.routes.append(
        StarletteRoute("/mcp", endpoint=mcp_asgi_handler, methods=["GET", "POST", "DELETE"]),
    )

    return app


def main() -> None:
    """Entry point for `metatron` CLI command."""
    settings = Settings()
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )
    uvicorn.run(
        "metatron.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.port,
        reload=settings.env == "development",
    )
