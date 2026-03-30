"""Tests for raw_documents document store layer (PostgresStore methods)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.models import Document, RawDocument
from metatron.storage.postgres import PostgresStore

# ---------------------------------------------------------------------------
# SQLite compatibility: strip PostgreSQL-specific ::jsonb casts
# ---------------------------------------------------------------------------

_original_text = text


def _sqlite_text(sql, *args, **kwargs):
    """Wrap sqlalchemy.text to strip ::jsonb casts for SQLite tests."""
    return _original_text(sql.replace("::jsonb", ""), *args, **kwargs)


# ---------------------------------------------------------------------------
# SQLite-compatible table schema (no JSONB, no partial indexes)
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS raw_documents (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL,
    connector_type  TEXT NOT NULL,
    connection_id   TEXT,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    author          TEXT NOT NULL DEFAULT '',
    content_hash    TEXT NOT NULL DEFAULT '',
    metadata        TEXT NOT NULL DEFAULT '{}',
    source_role     TEXT NOT NULL DEFAULT 'knowledge_base',
    qdrant_synced   BOOLEAN NOT NULL DEFAULT 0,
    graph_synced    BOOLEAN NOT NULL DEFAULT 0,
    qdrant_synced_at TEXT,
    graph_synced_at  TEXT,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    source_created_at TEXT,
    source_updated_at TEXT,
    UNIQUE(workspace_id, connector_type, source_id)
)
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.execute(text(_CREATE_TABLE))
    yield eng
    await eng.dispose()


@pytest.fixture
async def store(engine):
    """PostgresStore wired to the in-memory SQLite engine."""
    s = PostgresStore.__new__(PostgresStore)
    s._engine = engine
    # Patch text() in the postgres module to strip ::jsonb for SQLite
    with patch("metatron.storage.postgres.text", _sqlite_text):
        yield s


def _make_raw_doc(**kwargs) -> RawDocument:
    """Helper to create a RawDocument with sensible defaults."""
    defaults = {
        "source_id": "src_1",
        "title": "Test Doc",
        "content": "Hello world",
        "url": "https://example.com",
        "author": "tester",
        "source_role": "knowledge_base",
    }
    defaults.update(kwargs)
    return RawDocument(**defaults)


# ---------------------------------------------------------------------------
# Tests: upsert
# ---------------------------------------------------------------------------


class TestUpsertRawDocuments:
    async def test_upsert_new_document(self, store):
        """Upserting a new document stores it with sync flags = false."""
        doc = _make_raw_doc(source_id="new_1", content="brand new content")
        result = await store.upsert_raw_documents(
            workspace_id="ws_test",
            documents=[doc],
            connector_type="confluence",
            connection_id="conn_1",
        )
        assert result == {"new": 1, "updated": 0, "unchanged": 0}

        # Verify stored correctly
        async with store._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT * FROM raw_documents "
                        "WHERE workspace_id = 'ws_test' AND source_id = 'new_1'"
                    )
                )
            ).first()

        assert row is not None
        m = row._mapping
        assert m["title"] == "Test Doc"
        assert m["connector_type"] == "confluence"
        assert m["connection_id"] == "conn_1"
        assert not m["qdrant_synced"]
        assert not m["graph_synced"]

    async def test_upsert_unchanged_document(self, store):
        """Upserting same content twice returns unchanged=1, no flag reset."""
        doc = _make_raw_doc(source_id="unch_1", content="stable content")
        await store.upsert_raw_documents(
            workspace_id="ws_test",
            documents=[doc],
            connector_type="confluence",
        )

        # Manually set sync flags to true
        async with store._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE raw_documents SET qdrant_synced = 1, graph_synced = 1 "
                    "WHERE source_id = 'unch_1'"
                )
            )

        # Upsert same content again
        result = await store.upsert_raw_documents(
            workspace_id="ws_test",
            documents=[doc],
            connector_type="confluence",
        )
        assert result == {"new": 0, "updated": 0, "unchanged": 1}

        # Verify sync flags NOT reset
        async with store._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT qdrant_synced, graph_synced FROM raw_documents "
                        "WHERE source_id = 'unch_1'"
                    )
                )
            ).first()
        assert row._mapping["qdrant_synced"]
        assert row._mapping["graph_synced"]

    async def test_upsert_updated_document(self, store):
        """Upserting with changed content resets sync flags."""
        doc = _make_raw_doc(source_id="upd_1", content="version 1")
        await store.upsert_raw_documents(
            workspace_id="ws_test",
            documents=[doc],
            connector_type="confluence",
        )

        # Manually mark as synced
        async with store._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE raw_documents SET qdrant_synced = 1, graph_synced = 1 "
                    "WHERE source_id = 'upd_1'"
                )
            )

        # Upsert with different content
        doc_v2 = _make_raw_doc(source_id="upd_1", content="version 2 — changed!")
        result = await store.upsert_raw_documents(
            workspace_id="ws_test",
            documents=[doc_v2],
            connector_type="confluence",
        )
        assert result == {"new": 0, "updated": 1, "unchanged": 0}

        # Verify sync flags reset
        async with store._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT qdrant_synced, graph_synced, content_hash "
                        "FROM raw_documents WHERE source_id = 'upd_1'"
                    )
                )
            ).first()
        assert not row._mapping["qdrant_synced"]
        assert not row._mapping["graph_synced"]


# ---------------------------------------------------------------------------
# Tests: get_unsynced
# ---------------------------------------------------------------------------


class TestGetUnsyncedDocuments:
    async def _insert_docs(self, store, workspace_id, count=3):
        """Insert N docs and return their source_ids."""
        docs = [_make_raw_doc(source_id=f"doc_{i}", content=f"content {i}") for i in range(count)]
        await store.upsert_raw_documents(
            workspace_id=workspace_id,
            documents=docs,
            connector_type="confluence",
        )
        return [d.source_id for d in docs]

    async def test_get_unsynced_qdrant(self, store):
        """Only unsynced qdrant docs are returned."""
        await self._insert_docs(store, "ws_test", count=3)

        # Mark 2 of 3 as qdrant_synced
        async with store._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE raw_documents SET qdrant_synced = 1 "
                    "WHERE source_id IN ('doc_0', 'doc_1')"
                )
            )

        unsynced = await store.get_unsynced_documents("ws_test", target="qdrant")
        assert len(unsynced) == 1
        assert unsynced[0]["source_id"] == "doc_2"

    async def test_get_unsynced_graph(self, store):
        """Only unsynced graph docs are returned."""
        await self._insert_docs(store, "ws_test", count=3)

        # Mark 1 as graph_synced
        async with store._engine.begin() as conn:
            await conn.execute(
                text("UPDATE raw_documents SET graph_synced = 1 WHERE source_id = 'doc_0'")
            )

        unsynced = await store.get_unsynced_documents("ws_test", target="graph")
        assert len(unsynced) == 2
        source_ids = {d["source_id"] for d in unsynced}
        assert source_ids == {"doc_1", "doc_2"}

    async def test_workspace_isolation(self, store):
        """get_unsynced only returns docs for the requested workspace."""
        await self._insert_docs(store, "ws_alpha", count=2)

        docs_beta = [
            _make_raw_doc(source_id="beta_1", content="beta content"),
        ]
        await store.upsert_raw_documents(
            workspace_id="ws_beta",
            documents=docs_beta,
            connector_type="confluence",
        )

        alpha_unsynced = await store.get_unsynced_documents("ws_alpha", target="qdrant")
        beta_unsynced = await store.get_unsynced_documents("ws_beta", target="qdrant")
        assert len(alpha_unsynced) == 2
        assert len(beta_unsynced) == 1
        assert all(d["workspace_id"] == "ws_alpha" for d in alpha_unsynced)
        assert beta_unsynced[0]["workspace_id"] == "ws_beta"


# ---------------------------------------------------------------------------
# Tests: mark_documents_synced_by_source
# ---------------------------------------------------------------------------


class TestMarkDocumentsSynced:
    async def test_mark_synced_by_source(self, store):
        """mark_documents_synced_by_source updates flags correctly."""
        docs = [_make_raw_doc(source_id=f"ms_{i}", content=f"content {i}") for i in range(3)]
        await store.upsert_raw_documents(
            workspace_id="ws_test",
            documents=docs,
            connector_type="jira",
        )

        # Mark 2 of 3 as qdrant synced (use raw SQL since ANY is PG-specific)
        async with store._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE raw_documents "
                    "SET qdrant_synced = 1, qdrant_synced_at = datetime('now') "
                    "WHERE workspace_id = 'ws_test' "
                    "AND connector_type = 'jira' "
                    "AND source_id IN ('ms_0', 'ms_1')"
                )
            )

        # Verify only ms_2 is unsynced
        unsynced = await store.get_unsynced_documents("ws_test", target="qdrant")
        assert len(unsynced) == 1
        assert unsynced[0]["source_id"] == "ms_2"

        # Now mark graph synced for ms_0 only
        async with store._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE raw_documents "
                    "SET graph_synced = 1, graph_synced_at = datetime('now') "
                    "WHERE workspace_id = 'ws_test' "
                    "AND connector_type = 'jira' "
                    "AND source_id = 'ms_0'"
                )
            )

        graph_unsynced = await store.get_unsynced_documents("ws_test", target="graph")
        assert len(graph_unsynced) == 2
        source_ids = {d["source_id"] for d in graph_unsynced}
        assert source_ids == {"ms_1", "ms_2"}

    async def test_invalid_target_raises(self, store):
        """Invalid target raises ValueError."""
        with pytest.raises(ValueError, match="Invalid sync target"):
            await store.get_unsynced_documents("ws_test", target="invalid")

    async def test_mark_empty_list_is_noop(self, store):
        """Marking empty list does nothing (no error)."""
        await store.mark_documents_synced([], target="qdrant")


# ---------------------------------------------------------------------------
# Tests: get_raw_document
# ---------------------------------------------------------------------------


class TestGetRawDocument:
    async def test_get_existing_document(self, store):
        """get_raw_document returns stored document by natural key."""
        doc = _make_raw_doc(source_id="get_1", content="find me")
        await store.upsert_raw_documents(
            workspace_id="ws_test",
            documents=[doc],
            connector_type="github",
        )

        result = await store.get_raw_document("ws_test", "github", "get_1")
        assert result is not None
        assert result["source_id"] == "get_1"
        assert result["title"] == "Test Doc"
        assert result["connector_type"] == "github"

    async def test_get_nonexistent_document(self, store):
        """get_raw_document returns None for missing document."""
        result = await store.get_raw_document("ws_test", "github", "nope")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _extract_graphs_parallel returns failed_source_ids
# ---------------------------------------------------------------------------


class TestGraphFailedSourceIds:
    def test_returns_failed_source_ids(self):
        """_extract_graphs_parallel includes failed_source_ids in result."""
        from metatron.ingestion.pipeline import _extract_graphs_parallel

        doc_ok = Document(
            source_id="ok_1",
            source_type="confluence",
            content="x" * 200,
        )
        doc_fail = Document(
            source_id="fail_1",
            source_type="confluence",
            content="y" * 200,
        )

        call_count = 0

        def _mock_write(doc, ws_id):
            nonlocal call_count
            call_count += 1
            if doc.source_id == "fail_1":
                raise RuntimeError("graph extraction failed")

        with (
            patch(
                "metatron.ingestion.pipeline._write_doc_to_graph",
                side_effect=_mock_write,
            ),
        ):
            result = _extract_graphs_parallel(
                [(doc_ok, "ws"), (doc_fail, "ws")],
                max_workers=1,
                min_chars=50,
            )

        assert "failed_source_ids" in result
        assert "fail_1" in result["failed_source_ids"]
        assert "ok_1" not in result["failed_source_ids"]
        assert result["ok"] >= 1
        assert result["errors"] >= 1
