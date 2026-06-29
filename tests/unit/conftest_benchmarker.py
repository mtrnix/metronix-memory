"""Benchmarker test fixtures — in-memory SQLite, mocks for external deps.

Provides:
- In-memory SQLite engine + session (sync) for CRUD tests
- Mock Settings with benchmarker-relevant defaults
- Mock ConnectorRegistry, DocumentSampler
- Mocks for DeepSeek API, Embedding Proxy, BenchmarkQED, Qdrant
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from metronix.core.config import Settings
from metronix.storage.pg_models import Base

# ============================================================================
# In-memory SQLite engine & session
# ============================================================================


@pytest.fixture()
def sqlite_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Enable FK enforcement for SQLite
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """Provide a transactional SQLAlchemy session backed by SQLite."""
    factory = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def patch_get_session(db_session):
    """Patch ``metronix.storage.pg_connection.get_session`` to use SQLite.

    The patched context manager yields the same *db_session* and does NOT
    commit/rollback — the ``db_session`` fixture handles cleanup.
    """

    @contextmanager
    def _fake_get_session() -> Generator[Session, None, None]:
        yield db_session

    with patch("metronix.storage.pg_connection.get_session", _fake_get_session):
        yield


# ============================================================================
# Settings fixture (benchmarker-specific)
# ============================================================================


@pytest.fixture()
def bench_settings() -> Settings:
    """Settings with safe defaults for benchmarker tests."""
    return Settings(
        METRONIX_ENV="development",
        METRONIX_SECRET_KEY="test-secret-key",
        POSTGRES_HOST="localhost",
        POSTGRES_PASSWORD="test",
        FERNET_KEY="",
        DEEPSEEK_API_KEY="test-deepseek-key",
        DEEPSEEK_MODEL="deepseek-chat",
        BENCHMARKER_EMBEDDING_PROXY_URL="http://localhost:8001",
        QDRANT_HOST="localhost",
        QDRANT_HTTP_PORT=6333,
        OLLAMA_EMBED_MODEL="nomic-embed-text",
    )


# ============================================================================
# Mock external dependencies
# ============================================================================


@pytest.fixture()
def mock_deepseek_api():
    """Mock for DeepSeek API calls (LLM-as-Judge metrics)."""
    mock = AsyncMock()
    mock.return_value = {"choices": [{"message": {"content": '{"score": 0.85}'}}]}
    return mock


@pytest.fixture()
def mock_embedding_proxy():
    """Mock for Embedding Proxy (cosine similarity)."""
    mock = AsyncMock()
    mock.return_value = {"data": [{"embedding": [0.1] * 768}]}
    return mock


@pytest.fixture()
def mock_benchmark_qed():
    """Mock for BenchmarkQED (AutoQ / AutoE)."""
    mock = MagicMock()
    mock.agenerate = AsyncMock(return_value=MagicMock(selected_questions=[]))
    return mock


@pytest.fixture()
def mock_connector():
    """Mock connector implementing configure() and fetch()."""
    connector = AsyncMock()
    connector.configure = AsyncMock()
    connector.fetch = AsyncMock(return_value=[])
    return connector


@pytest.fixture()
def mock_connector_registry(mock_connector):
    """Mock ConnectorRegistry that returns the mock connector."""
    registry = MagicMock()
    registry.create.return_value = mock_connector
    return registry


@pytest.fixture()
def mock_qdrant():
    """Mock for Qdrant HTTP API responses."""
    mock = AsyncMock()
    mock.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "result": {
                "id": "chunk-1",
                "payload": {
                    "title": "Test Doc",
                    "data": "Test chunk content",
                    "doc_label": "test_doc",
                    "chunk": 0,
                    "type": "root",
                },
            }
        },
    )
    return mock


@pytest.fixture()
def mock_hybrid_search():
    """Mock for hybrid_search_and_answer with return_trace support."""

    def _search(
        query, user_id="user", k=5, workspace_id=None, intent_query=None, return_trace=False
    ):
        answer = f"Answer for: {query}"
        if return_trace:
            return {
                "answer": answer,
                "source_results": [{"id": "src-1", "score": 0.9}],
                "fragments": ["fragment-1"],
                "graph_entities": [{"name": "Entity1"}],
                "graph_relations": [{"source": "A", "target": "B"}],
                "graph_docs": [{"doc_label": "doc1"}],
            }
        return answer

    return MagicMock(side_effect=_search)
