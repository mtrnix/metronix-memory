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

from metatron.api.routes import (
    admin,
    benchmarker,
    chat,
    connections,
    files,
    health,
    skills,
    sync,
    workspaces,
)
from metatron.core.config import Settings
from metatron.core.logging import configure_logging

logger = structlog.get_logger()


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

    # CORS — default "*" for development, restrict via CORS_ORIGINS in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route modules
    app.include_router(health.router)
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(connections.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")
    app.include_router(benchmarker.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")

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
