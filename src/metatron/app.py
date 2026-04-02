"""Unified entry point — runs API server and channel bots in one process.

Starts FastAPI (uvicorn) and messaging channels (Telegram, Discord, Slack)
as concurrent async tasks sharing a single AgentRouter instance. Channels
are started dynamically based on enabled connections in the database.

Usage:
    python -m metatron.app
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
import uvicorn

from metatron.agent.router import AgentRouter
from metatron.api.app import create_app
from metatron.core.config import Settings
from metatron.core.logging import configure_logging

logger = structlog.get_logger()


async def _run_api(
    settings: Settings,
    channel_manager: Any | None = None,
) -> None:
    """Run FastAPI via uvicorn as an async server."""
    app = create_app(settings)
    if channel_manager is not None:
        app.state.channel_manager = channel_manager
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_all() -> None:
    """Start all configured services in a single event loop."""
    settings = Settings()
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )

    router = AgentRouter(settings=settings)

    # One-time migration: env-var credentials → DB connections (idempotent)
    try:
        from metatron.storage.migrate_env_connections import migrate_env_to_db

        mig = await migrate_env_to_db(
            postgres_dsn=settings.postgres_dsn,
            workspace_id=settings.default_workspace_id,
            fernet_key=settings.fernet_key,
        )
        if mig["created"]:
            logger.info(
                "app.env_migration.done",
                created=mig["created"],
            )
    except Exception as exc:
        logger.warning(
            "app.env_migration.failed",
            error=str(exc),
        )

    # Create channel manager (shared store instance)
    from metatron.channels.manager import ChannelManager
    from metatron.storage.postgres import PostgresStore

    store = PostgresStore(settings.postgres_dsn)

    # Platform user mapper — resolves channel identities to internal users
    mapper = None
    event_bus = None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        from metatron.auth.user_mapping import PlatformUserMapper
        from metatron.auth.user_store import UserStore
        from metatron.core.events import EventBus

        _engine = create_async_engine(settings.postgres_dsn)
        _user_store = UserStore(_engine)
        await _user_store.ensure_schema()
        mapper = PlatformUserMapper(_engine, _user_store)
        await mapper.ensure_schema()
        event_bus = EventBus()
        logger.info("app.user_mapper.ready")
    except Exception as exc:
        logger.warning("app.user_mapper.init_failed", error=str(exc))

    channel_manager = ChannelManager(
        router=router,
        store=store,
        mapper=mapper,
        event_bus=event_bus,
    )
    try:
        started = await channel_manager.start_channels_from_db(
            fernet_key=settings.fernet_key,
            default_workspace_id=settings.default_workspace_id,
        )
        logger.info("app.channels.started", count=started)
    except Exception as exc:
        logger.error(
            "app.channels.startup_failed",
            error=str(exc),
            exc_info=True,
        )

    tasks: list[asyncio.Task] = []

    # API server — always runs (pass channel_manager for dynamic channel start)
    tasks.append(
        asyncio.create_task(
            _run_api(settings, channel_manager=channel_manager),
        )
    )
    logger.info("app.api.scheduled", port=settings.port)

    logger.info("app.starting", services=len(tasks))

    try:
        await asyncio.gather(*tasks)
    finally:
        await channel_manager.stop_all()
        await store.close()


def main() -> None:
    """CLI entry point for unified launcher."""
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
