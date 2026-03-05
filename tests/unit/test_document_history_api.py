"""Tests for api/routes/documents.py — document history endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.routes.documents import router
from metatron.core.models import DocumentVersion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_postgres() -> FastAPI:
    """Create a minimal FastAPI app with mocked postgres store."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    mock_postgres = AsyncMock()
    app.state.postgres = mock_postgres
    return app


@pytest.fixture
def client(app_with_postgres: FastAPI) -> TestClient:
    return TestClient(app_with_postgres, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetDocumentHistory:
    def test_returns_versions(self, app_with_postgres: FastAPI) -> None:
        versions = [
            DocumentVersion(
                id="v2",
                document_id="doc1",
                version_number=2,
                content="Updated content here",
                content_hash="hash2",
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
                sync_source="confluence",
                changed_fields={"content": ["old", "new"]},
            ),
            DocumentVersion(
                id="v1",
                document_id="doc1",
                version_number=1,
                content="Original",
                content_hash="hash1",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                sync_source="manual",
            ),
        ]
        app_with_postgres.state.postgres.get_document_history = AsyncMock(
            return_value=(versions, 2),
        )

        client = TestClient(app_with_postgres, raise_server_exceptions=False)
        r = client.get("/api/v1/documents/doc1/history")
        assert r.status_code == 200
        body = r.json()
        assert body["document_id"] == "doc1"
        assert body["total"] == 2
        assert len(body["versions"]) == 2
        assert body["versions"][0]["version_number"] == 2
        assert body["versions"][0]["sync_source"] == "confluence"
        assert body["has_more"] is False

    def test_pagination_params(self, app_with_postgres: FastAPI) -> None:
        app_with_postgres.state.postgres.get_document_history = AsyncMock(
            return_value=([], 0),
        )

        client = TestClient(app_with_postgres, raise_server_exceptions=False)
        r = client.get("/api/v1/documents/doc1/history?limit=5&offset=10")
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 5
        assert body["offset"] == 10

    def test_has_more_when_paginated(self, app_with_postgres: FastAPI) -> None:
        app_with_postgres.state.postgres.get_document_history = AsyncMock(
            return_value=([], 50),
        )

        client = TestClient(app_with_postgres, raise_server_exceptions=False)
        r = client.get("/api/v1/documents/doc1/history?limit=10&offset=0")
        body = r.json()
        assert body["has_more"] is True

    def test_content_preview_truncation(self, app_with_postgres: FastAPI) -> None:
        long_content = "x" * 500
        versions = [
            DocumentVersion(
                id="v1",
                document_id="doc1",
                version_number=1,
                content=long_content,
                content_hash="h",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]
        app_with_postgres.state.postgres.get_document_history = AsyncMock(
            return_value=(versions, 1),
        )

        client = TestClient(app_with_postgres, raise_server_exceptions=False)
        r = client.get("/api/v1/documents/doc1/history")
        body = r.json()
        preview = body["versions"][0]["content_preview"]
        assert len(preview) == 203  # 200 + "..."
        assert preview.endswith("...")

    def test_503_when_postgres_not_initialized(self) -> None:
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        # No app.state.postgres set
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/documents/doc1/history")
        assert r.status_code == 503

    def test_500_on_db_error(self, app_with_postgres: FastAPI) -> None:
        app_with_postgres.state.postgres.get_document_history = AsyncMock(
            side_effect=RuntimeError("DB connection lost"),
        )

        client = TestClient(app_with_postgres, raise_server_exceptions=False)
        r = client.get("/api/v1/documents/doc1/history")
        assert r.status_code == 500
