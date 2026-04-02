"""Programmatic Alembic migration runner.

Called from the FastAPI lifespan to auto-apply pending migrations on startup.
Uses a PostgreSQL advisory lock so only one replica migrates at a time when
multiple instances start simultaneously.

Advisory lock ID is derived from the project name so it doesn't collide with
other applications sharing the same PostgreSQL cluster.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Stable 64-bit advisory lock ID — derived from project name.
# pg_try_advisory_lock takes bigint, so cap to signed 64-bit range.
_LOCK_ID: int = int(hashlib.md5(b"metatron_migrations").hexdigest()[:15], 16) % (2**63)


def _find_alembic_ini() -> str:
    """Locate alembic.ini.

    Search order:
    1. cwd/alembic.ini  — production / Docker (WORKDIR = project root)
    2. <package root>/alembic.ini — editable installs and local dev
    """
    cwd_candidate = Path.cwd() / "alembic.ini"
    if cwd_candidate.exists():
        return str(cwd_candidate)

    # This file: src/metatron/storage/migrations.py → parents[3] = project root
    src_candidate = Path(__file__).parents[3] / "alembic.ini"
    if src_candidate.exists():
        return str(src_candidate)

    raise FileNotFoundError(
        "alembic.ini not found. Run from the project root or set WORKDIR correctly in Docker."
    )


def run_migrations_sync(sync_dsn: str, async_dsn: str) -> None:
    """Apply pending Alembic migrations.

    Uses a PostgreSQL advisory lock to prevent race conditions when multiple
    replicas start at the same time — only one acquires the lock and runs
    migrations; the others wait and then return immediately (already at head).

    The project's env.py is async (uses asyncpg), so two DSNs are needed:
    - ``sync_dsn``  — psycopg2 URL for the advisory lock connection
    - ``async_dsn`` — asyncpg URL passed to alembic config (matches env.py)

    Args:
        sync_dsn:  Synchronous DSN  ``postgresql://user:pass@host/db``
        async_dsn: Async DSN        ``postgresql+asyncpg://user:pass@host/db``

    Raises:
        Re-raises exceptions after releasing the advisory lock.
        Callers (lifespan) should treat failures as non-fatal.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    alembic_ini = _find_alembic_ini()
    # Sync engine used only for the advisory lock — not for running migrations.
    engine = create_engine(sync_dsn, pool_pre_ping=True)

    with engine.connect() as conn:
        # Try non-blocking lock first
        locked: bool = conn.execute(text(f"SELECT pg_try_advisory_lock({_LOCK_ID})")).scalar()

        if not locked:
            # Another replica holds the lock and is currently migrating.
            # Block until it releases, then return — schema is already at head.
            logger.info("migrations.waiting_for_lock", lock_id=_LOCK_ID)
            conn.execute(text(f"SELECT pg_advisory_lock({_LOCK_ID})"))
            conn.execute(text(f"SELECT pg_advisory_unlock({_LOCK_ID})"))
            logger.info("migrations.lock_released_by_peer")
            conn.commit()
            return

        try:
            # env.py is async (asyncpg) — pass the async DSN so it can build
            # the async engine; the sync engine above is only for the lock.
            alembic_cfg = Config(alembic_ini)
            alembic_cfg.set_main_option("sqlalchemy.url", async_dsn)
            command.upgrade(alembic_cfg, "head")
            logger.info("migrations.applied", alembic_ini=alembic_ini)
        finally:
            conn.execute(text(f"SELECT pg_advisory_unlock({_LOCK_ID})"))
            conn.commit()

    engine.dispose()
