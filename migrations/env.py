"""Alembic environment configuration for async PostgreSQL migrations."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from dotenv import load_dotenv

load_dotenv()

from alembic import context  # noqa: E402
from sqlalchemy import pool  # noqa: E402
from sqlalchemy.ext.asyncio import async_engine_from_config  # noqa: E402

config = context.config
# Only run Alembic's `fileConfig` when the host process has not already
# configured logging. Inside the API lifespan, `core.logging.configure_logging`
# attaches `_FlushingStreamHandler` to the root logger BEFORE migrations run;
# running `fileConfig` on top would either wipe that handler (default
# behaviour) or attach Alembic's stderr console handler in parallel and emit
# every line twice. Standalone `alembic upgrade` invocations have no handlers
# on root at this point, so the .ini config still kicks in there.
import logging  # noqa: E402 — local import keeps the top-level surface clean

if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name)

target_metadata = None

# Override alembic.ini DSN with POSTGRES_* env vars when present, so
# `make migrate` and the app lifespan hit the same database.
if os.environ.get("POSTGRES_HOST"):
    _host = os.environ.get("POSTGRES_HOST", "localhost")
    _port = os.environ.get("POSTGRES_PORT", "5432")
    _user = os.environ.get("POSTGRES_USER", "metronix")
    _pass = os.environ.get("POSTGRES_PASSWORD", "metronix_dev")
    _db = os.environ.get("POSTGRES_DB", "metronix")
    config.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{_user}:{_pass}@{_host}:{_port}/{_db}",
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without a live connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
