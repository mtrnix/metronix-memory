"""FastAPI application factory.

Creates and configures the FastAPI app with all routers,
middleware, and lifespan events. Uses the factory pattern
so tests can create isolated app instances.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from metatron.api.middleware import OptionalAuthMiddleware
from metatron.api.routes import (
    admin,
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
    skills,
    sync,
    workspaces,
)
from metatron.core.config import Settings
from metatron.core.logging import configure_logging
from metatron.core.plugin import PluginManager, discover_plugins

logger = structlog.get_logger()


# MCP server instance — imported to register tools
from metatron.mcp.server import mcp as mcp_server
import metatron.mcp.tools  # noqa: F401 — registers @mcp.tool() decorators


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

    # TODO: initialize stores and services
    # app.state.postgres = PostgresStore(settings.postgres_dsn)
    # app.state.qdrant = QdrantVectorStore(...)
    # app.state.memgraph = MemgraphGraphStore(...)
    # app.state.ollama = OllamaProvider(...)
    # Register builtins: register_builtins(app.state.connector_registry)

    # Initialize MCP session manager (required for streamable-http transport)
    async with mcp_server.session_manager.run():
        logger.info("mcp.session_manager.started")
        yield

    # Shutdown: close all connections
    logger.info("app.shutdown")
    # TODO: close stores
    # await app.state.postgres.close()
    # await app.state.qdrant.close()
    # await app.state.memgraph.close()


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
    )
    app.state.settings = settings

    # --- Plugin discovery (must happen before middleware/routes) ---
    plugin_manager = PluginManager()
    discover_plugins(plugin_manager)
    app.state.plugin_manager = plugin_manager

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

    from metatron.api.routes.finops import router as finops_router
    app.include_router(finops_router, prefix="/api/v1")

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
