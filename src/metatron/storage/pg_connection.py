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


def store_rag_trace_sync(trace: dict) -> None:
    """Persist one RAG debug trace synchronously (called via asyncio.to_thread).

    ``trace`` is the full ``RagTrace.to_dict()`` payload. Never raises — a write
    failure must not break the answer path; it is logged at WARNING and dropped.
    """
    from datetime import UTC, datetime

    from metatron.storage.pg_models import RagDebugTraceRow

    trace_id = trace.get("trace_id")
    if not trace_id:
        logger.warning("postgres.rag_trace.store_skipped_no_id")
        return

    try:
        with get_session() as session:
            row = RagDebugTraceRow(
                trace_id=trace_id,
                workspace_id=trace.get("workspace_id"),
                user_id=trace.get("user_id"),
                agent_id=trace.get("agent_id"),
                source=trace.get("source"),
                query=(trace.get("input") or {}).get("raw_user_message") or "",
                total_ms=float(trace.get("total_ms") or 0.0),
                trace=trace,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.commit()
        logger.info("postgres.rag_trace.stored", trace_id=trace_id)
    except Exception as e:
        logger.warning("postgres.rag_trace.store_failed", trace_id=trace_id, error=str(e))


def get_rag_trace_sync(workspace_id: str, trace_id: str) -> dict | None:
    """Fetch one trace's JSONB payload, workspace-scoped. None if absent/cross-workspace."""
    from metatron.storage.pg_models import RagDebugTraceRow

    with get_session() as session:
        row = (
            session.query(RagDebugTraceRow)
            .filter(
                RagDebugTraceRow.trace_id == trace_id,
                RagDebugTraceRow.workspace_id == workspace_id,
            )
            .first()
        )
        if row is None:
            return None
        # Merge the row's created_at into the JSONB payload (column, not stored in trace).
        payload = dict(row.trace)
        payload["created_at"] = row.created_at.isoformat() if row.created_at else None
        return payload


def list_rag_traces_sync(workspace_id: str, limit: int, offset: int) -> list[dict]:
    """List recent traces for a workspace (newest-first), lightweight rows (no JSONB)."""
    from metatron.storage.pg_models import RagDebugTraceRow

    with get_session() as session:
        rows = (
            session.query(RagDebugTraceRow)
            .filter(RagDebugTraceRow.workspace_id == workspace_id)
            .order_by(RagDebugTraceRow.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [
            {
                "trace_id": r.trace_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "query": r.query,
                "source": r.source,
                "total_ms": r.total_ms,
            }
            for r in rows
        ]


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
