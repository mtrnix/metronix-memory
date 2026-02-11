"""PostgreSQL sync connection management.

Migrated from PoC metatron/postgres/connection.py.
Provides SQLAlchemy engine and session with connection pooling.

# TODO: async migration — replace with asyncpg/SQLAlchemy async engine
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from threading import Lock
from typing import Generator

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

logger = structlog.get_logger()

_engine = None
_session_factory = None
_engine_lock = Lock()


def get_engine(dsn: str | None = None):
    """Get shared SQLAlchemy engine instance.

    Creates engine on first call with connection pooling.
    """
    global _engine

    if _engine is None:
        with _engine_lock:
            if _engine is None:
                if dsn is None:
                    from metatron.core.config import Settings
                    settings = Settings()
                    dsn = settings.postgres_sync_dsn

                if not dsn:
                    raise ValueError("POSTGRES_URL is not configured.")

                _engine = create_engine(
                    dsn,
                    pool_size=10,
                    max_overflow=20,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    echo=False,
                )
                logger.info("postgres.engine.initialized", pool_size=10)

    return _engine


def get_session_factory():
    """Get or create session factory."""
    global _session_factory

    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
        )

    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a database session as context manager.

    Automatically commits on success, rolls back on exception.
    """
    factory = get_session_factory()
    session = factory()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Initialize database — create all tables."""
    from metatron.storage.pg_models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("postgres.tables.initialized")


def close_db() -> None:
    """Close database connections."""
    global _engine, _session_factory

    if _engine is not None:
        with _engine_lock:
            if _engine is not None:
                _engine.dispose()
                _engine = None
                _session_factory = None
                logger.info("postgres.engine.closed")


atexit.register(close_db)
