"""FastAPI application factory.

Creates and configures the FastAPI app with all routers,
middleware, and lifespan events. Uses the factory pattern
so tests can create isolated app instances.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from metatron.api.middleware import OptionalAuthMiddleware
from metatron.api.routes import (
    admin,
    auth,
    benchmarker,
    chat,
    connections,
    documents,
    files,
    health,
    skills,
    sync,
    workspaces,
)
from metatron.core.config import Settings
from metatron.core.logging import configure_logging
from metatron.ingestion.sync import BackgroundSyncManager

logger = structlog.get_logger()


# MCP server instance - imported to register tools
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

    # TODO: initialize stores and services
    # app.state.postgres = PostgresStore(settings.postgres_dsn)
    # app.state.qdrant = QdrantVectorStore(...)
    # app.state.memgraph = MemgraphGraphStore(...)
    # app.state.ollama = OllamaProvider(...)
    # Register builtins: register_builtins(app.state.connector_registry)

    # Initialize and start background sync manager
    sync_interval = getattr(settings, "sync_interval_seconds", 3600)  # default 1 hour
    sync_sources = ["confluence", "jira", "notion"]  # TODO: make configurable
    sync_manager = BackgroundSyncManager(
        sync_interval_seconds=sync_interval,
        sources=sync_sources,
    )
    await sync_manager.start()
    app.state.sync_manager = sync_manager
    logger.info("BackgroundSyncManager started", interval_seconds=sync_interval)

    yield

    # Shutdown: stop sync manager and close all connections
    logger.info("app.shutdown")
    await sync_manager.stop()
    
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

    # CORS — credentials are only safe with explicit origins, not wildcard
    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth middleware (checked after CORS)
    app.add_middleware(OptionalAuthMiddleware)

    # Register route modules
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
    app.include_router(files.router, prefix="/api/v1")

    # Mount MCP server at /mcp
    # Using streamable-http transport with shared lifespan
    mcp_app = mcp_server.streamable_http_app()

    # Mount with shared lifespan
    app.mount("/mcp", mcp_app)

    # Add MCP health check endpoint
    @app.get("/mcp")
    async def mcp_health():
        """MCP server health check."""
        return {
            "status": "ok",
            "server": "MetatronMCP",
            "path": "/mcp",
            "transport": "streamable-http",
        }

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
