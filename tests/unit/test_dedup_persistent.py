"""Tests for persistent deduplication index (MTRNIX-213)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.ingestion.dedup import DeduplicationIndex, simhash
from metatron.storage.postgres import (
    PostgresStore,
    _from_pg_bigint,
    _to_pg_bigint,
)

# ---------------------------------------------------------------------------
# SQLite compatibility
# ---------------------------------------------------------------------------

_original_text = text


def _sqlite_text(sql, *args, **kwargs):
    """Wrap sqlalchemy.text to strip PG-specific casts for SQLite."""
    return _original_text(sql.replace("::jsonb", ""), *args, **kwargs)


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS dedup_fingerprints (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL,
    doc_label       TEXT NOT NULL,
    fingerprint     INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workspace_id, fingerprint, doc_label)
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
    """PostgresStore wired to in-memory SQLite."""
    s = PostgresStore.__new__(PostgresStore)
    s._engine = engine
    with patch("metatron.storage.postgres.text", _sqlite_text):
        yield s


# ---------------------------------------------------------------------------
# Tests: DeduplicationIndex persistence features
# ---------------------------------------------------------------------------


class TestLoadPreloadsFingerprints:
    def test_load_preloads_fingerprints(self):
        """load() makes check_and_add detect cross-doc dups."""
        idx = DeduplicationIndex()
        text_a = "the quick brown fox jumps over the lazy dog near the river"
        fp = simhash(text_a)

        # Pre-load fingerprint from "doc_A"
        idx.load({fp: "doc_A"})

        # Same text from "doc_B" should be detected as duplicate
        is_dup = idx.check_and_add(text_a, "doc_B")
        assert is_dup is True

    def test_load_same_doc_not_flagged(self):
        """load() does not flag same-doc chunks as dups."""
        idx = DeduplicationIndex()
        text_a = "the quick brown fox jumps over the lazy dog near the river"
        fp = simhash(text_a)

        idx.load({fp: "doc_A"})

        # Same doc re-ingest should not be flagged
        is_dup = idx.check_and_add(text_a, "doc_A")
        assert is_dup is False


class TestGetNewFingerprints:
    def test_get_new_fingerprints(self):
        """Only new additions (not loaded) are returned."""
        idx = DeduplicationIndex()
        existing_text = "existing content that was already indexed before"
        fp = simhash(existing_text)
        idx.load({fp: "old_doc"})

        # Add new content
        new_text = "brand new unique content for testing dedup persistence"
        idx.check_and_add(new_text, "new_doc")

        new_fps = idx.get_new_fingerprints()
        assert len(new_fps) == 1
        assert new_fps[0][0] == "new_doc"
        assert new_fps[0][1] == simhash(new_text)

    def test_loaded_not_in_new(self):
        """Loaded fingerprints are not returned as new."""
        idx = DeduplicationIndex()
        idx.load({12345: "doc_A"})

        new_fps = idx.get_new_fingerprints()
        assert len(new_fps) == 0


class TestRemoveDocClearsNew:
    def test_remove_doc_clears_new(self):
        """remove_doc() cleans both _hashes and _new_fingerprints."""
        idx = DeduplicationIndex()
        text_a = "some unique text for document alpha testing"
        text_b = "another unique text for document beta testing"

        idx.check_and_add(text_a, "doc_A")
        idx.check_and_add(text_b, "doc_B")
        assert len(idx.get_new_fingerprints()) == 2

        idx.remove_doc("doc_A")

        assert len(idx) == 1
        new_fps = idx.get_new_fingerprints()
        assert len(new_fps) == 1
        assert new_fps[0][0] == "doc_B"


# ---------------------------------------------------------------------------
# Tests: BIGINT conversion
# ---------------------------------------------------------------------------


class TestBigintConversion:
    def test_roundtrip_small_value(self):
        """Small values round-trip correctly."""
        assert _from_pg_bigint(_to_pg_bigint(42)) == 42

    def test_roundtrip_near_boundary(self):
        """Values near 2^63 boundary round-trip correctly."""
        boundary = (1 << 63) - 1  # max signed positive
        assert _from_pg_bigint(_to_pg_bigint(boundary)) == boundary

        over = 1 << 63  # exactly at boundary
        assert _to_pg_bigint(over) < 0
        assert _from_pg_bigint(_to_pg_bigint(over)) == over

    def test_roundtrip_large_value(self):
        """Large unsigned values (above 2^63) round-trip correctly."""
        large = (1 << 64) - 1  # max unsigned 64-bit
        pg_val = _to_pg_bigint(large)
        assert pg_val == -1  # wraps to -1 in signed space
        assert _from_pg_bigint(pg_val) == large

    def test_roundtrip_zero(self):
        """Zero round-trips correctly."""
        assert _from_pg_bigint(_to_pg_bigint(0)) == 0


# ---------------------------------------------------------------------------
# Tests: PostgresStore batch_load / save (SQLite-backed)
# ---------------------------------------------------------------------------


class TestBatchLoadAndSave:
    async def test_save_and_load_roundtrip(self, store):
        """save_fingerprints → batch_load_fingerprints returns same data."""
        fps = [("doc_1", 100), ("doc_1", 200), ("doc_2", 300)]
        inserted = await store.save_fingerprints("ws_test", fps)
        assert inserted == 3

        loaded = await store.batch_load_fingerprints("ws_test")
        assert loaded == {100: "doc_1", 200: "doc_1", 300: "doc_2"}

    async def test_save_dedup_on_conflict(self, store):
        """Duplicate (workspace, fingerprint, doc_label) is skipped."""
        fps = [("doc_1", 100)]
        await store.save_fingerprints("ws_test", fps)
        inserted = await store.save_fingerprints("ws_test", fps)
        assert inserted == 0

    async def test_delete_by_doc(self, store):
        """delete_fingerprints_by_doc removes only that doc's FPs."""
        fps = [("doc_1", 100), ("doc_1", 200), ("doc_2", 300)]
        await store.save_fingerprints("ws_test", fps)

        deleted = await store.delete_fingerprints_by_doc("ws_test", "doc_1")
        assert deleted == 2

        loaded = await store.batch_load_fingerprints("ws_test")
        assert loaded == {300: "doc_2"}

    async def test_workspace_isolation(self, store):
        """Fingerprints from different workspaces don't mix."""
        await store.save_fingerprints("ws_a", [("doc_1", 100)])
        await store.save_fingerprints("ws_b", [("doc_2", 200)])

        loaded_a = await store.batch_load_fingerprints("ws_a")
        loaded_b = await store.batch_load_fingerprints("ws_b")

        assert loaded_a == {100: "doc_1"}
        assert loaded_b == {200: "doc_2"}

    async def test_save_empty_list(self, store):
        """Saving empty list returns 0, no error."""
        inserted = await store.save_fingerprints("ws_test", [])
        assert inserted == 0
