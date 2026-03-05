"""Tests for document versioning — models, migration, and postgres store methods."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.core.models import DocumentVersion


class TestDocumentVersionModel:
    def test_defaults(self) -> None:
        v = DocumentVersion()
        assert v.version_number == 1
        assert v.content == ""
        assert v.sync_source == "manual"
        assert v.changed_fields == {}
        assert v.id  # auto-generated

    def test_custom_fields(self) -> None:
        v = DocumentVersion(
            id="v1",
            document_id="doc1",
            version_number=3,
            content="hello",
            content_hash="abc",
            sync_source="confluence",
            changed_fields={"title": ["old", "new"]},
        )
        assert v.document_id == "doc1"
        assert v.version_number == 3
        assert v.changed_fields["title"] == ["old", "new"]

    def test_content_hash_computation(self) -> None:
        content = "test content"
        expected = hashlib.sha256(content.encode()).hexdigest()
        v = DocumentVersion(content=content, content_hash=expected)
        assert v.content_hash == expected

    def test_created_at_is_utc(self) -> None:
        v = DocumentVersion()
        assert v.created_at.tzinfo is not None


class TestPostgresStoreVersioning:
    """Test PostgresStore document versioning methods with mocked DB."""

    @pytest.fixture
    def store(self) -> MagicMock:
        """Create a mock PostgresStore for unit testing."""
        from metatron.storage.postgres import PostgresStore

        # We can't easily instantiate PostgresStore without a real DSN,
        # so we test the _row_to_version helper directly
        return PostgresStore.__new__(PostgresStore)

    def test_row_to_version_with_mapping(self, store: MagicMock) -> None:
        """Test the _row_to_version static helper."""
        now = datetime(2026, 1, 1, tzinfo=UTC)
        mock_row = MagicMock()
        mock_row._mapping = {
            "id": "v1",
            "document_id": "d1",
            "version_number": 2,
            "content": "hello",
            "content_hash": "abc123",
            "created_at": now,
            "changed_fields": {"title": ["old", "new"]},
            "sync_source": "jira",
        }

        from metatron.storage.postgres import PostgresStore

        version = PostgresStore._row_to_version(mock_row)

        assert version.id == "v1"
        assert version.document_id == "d1"
        assert version.version_number == 2
        assert version.content == "hello"
        assert version.sync_source == "jira"
        assert version.changed_fields == {"title": ["old", "new"]}

    def test_row_to_version_naive_datetime(self, store: MagicMock) -> None:
        """Test that naive datetimes get UTC timezone attached."""
        naive_dt = datetime(2026, 1, 1)  # No tzinfo
        mock_row = MagicMock()
        mock_row._mapping = {
            "id": "v1",
            "document_id": "d1",
            "version_number": 1,
            "content": "x",
            "content_hash": "h",
            "created_at": naive_dt,
            "changed_fields": {},
            "sync_source": "manual",
        }

        from metatron.storage.postgres import PostgresStore

        version = PostgresStore._row_to_version(mock_row)
        assert version.created_at.tzinfo == UTC

    def test_row_to_version_null_changed_fields(self, store: MagicMock) -> None:
        """Test that None changed_fields becomes empty dict."""
        now = datetime(2026, 1, 1, tzinfo=UTC)
        mock_row = MagicMock()
        mock_row._mapping = {
            "id": "v1",
            "document_id": "d1",
            "version_number": 1,
            "content": "x",
            "content_hash": "h",
            "created_at": now,
            "changed_fields": None,
            "sync_source": "manual",
        }

        from metatron.storage.postgres import PostgresStore

        version = PostgresStore._row_to_version(mock_row)
        assert version.changed_fields == {}
