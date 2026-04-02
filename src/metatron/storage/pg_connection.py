"""PostgreSQL sync connection management.

Migrated from PoC metatron/postgres/connection.py.
Provides SQLAlchemy engine and session with connection pooling.

# TODO: async migration — replace with asyncpg/SQLAlchemy async engine
"""

from __future__ import annotations

import atexit
from collections.abc import Generator
from contextlib import contextmanager
from threading import Lock

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


def store_query_trace_sync(
    workspace_id: str,
    query: str,
    trace: dict,
    total_ms: float,
) -> str:
    """Store a query trace synchronously (for use in sync code).

    Args:
        workspace_id: Workspace this query belongs to.
        query: The user query text.
        trace: Trace data (timing, results, etc.) as dict.
        total_ms: Total query execution time in milliseconds.

    Returns:
        ID of the stored trace.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from metatron.storage.pg_models import QueryTraceRow

    trace_id = uuid4().hex

    try:
        with get_session() as session:
            trace_row = QueryTraceRow(
                id=trace_id,
                workspace_id=workspace_id,
                query=query,
                trace=trace,  # SQLAlchemy handles JSONB serialization
                total_ms=total_ms,
                created_at=datetime.now(UTC),
            )
            session.add(trace_row)
            session.commit()

        logger.info(
            "postgres.query_trace.stored",
            trace_id=trace_id,
            workspace_id=workspace_id,
            total_ms=total_ms,
        )
    except Exception as e:
        logger.warning(
            "postgres.query_trace.store_failed",
            workspace_id=workspace_id,
            error=str(e),
        )
        # Don't fail the query if trace storage fails

    return trace_id


def upsert_document_fetch_stats_sync(
    workspace_id: str,
    doc_stats: dict[str, dict],
) -> None:
    """Upsert per-day document fetch statistics (fire-and-forget).

    Args:
        workspace_id: Workspace this query belongs to.
        doc_stats: {doc_label: {"title": str, "word_count": int, "fetch_count": int}}
    """
    if not doc_stats:
        return

    from datetime import UTC, date, datetime

    from sqlalchemy.dialects.postgresql import insert

    from metatron.storage.pg_models import DocumentFetchStatsRow

    today = date.today()
    rows = [
        {
            "workspace_id": workspace_id,
            "doc_label": dl,
            "title": info["title"],
            "fetch_count": info["fetch_count"],
            "total_context_words": info["word_count"],
            "fetch_date": today,
            "created_at": datetime.now(UTC),
        }
        for dl, info in doc_stats.items()
    ]

    try:
        with get_session() as session:
            stmt = insert(DocumentFetchStatsRow).values(rows)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_doc_fetch_stats",
                set_={
                    "title": stmt.excluded.title,
                    "fetch_count": DocumentFetchStatsRow.fetch_count + stmt.excluded.fetch_count,
                    "total_context_words": DocumentFetchStatsRow.total_context_words
                    + stmt.excluded.total_context_words,
                },
            )
            session.execute(stmt)
            session.commit()

        logger.info(
            "postgres.doc_fetch_stats.upserted",
            workspace_id=workspace_id,
            doc_count=len(doc_stats),
        )
    except Exception as e:
        logger.warning(
            "postgres.doc_fetch_stats.upsert_failed",
            workspace_id=workspace_id,
            error=str(e),
        )
