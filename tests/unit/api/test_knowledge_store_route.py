"""Tests for POST /api/v1/knowledge/store.

Mirrors the request/response contract of the metronix_store MCP tool
(tests/unit/test_mcp_tools.py::TestMetronixStore) -- both entry points call
the same metronix.ingestion.store.store_document() helper.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from metronix.api.routes.knowledge import router as knowledge_router
from metronix.auth.dependencies import get_current_user
from metronix.core.models import Role, User


def _make_user(role: Role = Role.EDITOR) -> User:
    return User(
        id="u1",
        username="tester",
        email="t@example.com",
        role=role,
        workspace_ids=["ws-test"],
    )


def _make_client(role: Role = Role.EDITOR) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _make_user(role=role)

    @app.middleware("http")
    async def _inject_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user = {"workspace_ids": ["ws-test"]}
        return await call_next(request)

    return TestClient(app, raise_server_exceptions=False)


def test_store_document_success():
    mock_result = MagicMock()
    mock_result.errors = []
    mock_result.documents_new = 3
    with (
        patch("metronix.mcp.tools._source_deps.get_store", return_value=AsyncMock()),
        patch("metronix.ingestion.sync.persist_raw_documents", new_callable=AsyncMock),
        patch(
            "metronix.ingestion.pipeline.ingest_documents",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        client = _make_client()
        response = client.post(
            "/api/v1/knowledge/store?workspace_id=ws-test",
            json={
                "content": "Wiki page body",
                "title": "Page",
                "doc_label": "hermes-wiki-abc123",
                "source_type": "hermes_llm_wiki",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["doc_label"] == "hermes-wiki-abc123"
    assert body["chunks_stored"] == 3


def test_store_document_empty_content_returns_400():
    client = _make_client()

    response = client.post(
        "/api/v1/knowledge/store?workspace_id=ws-test",
        json={"content": "   "},
    )

    assert response.status_code == 400


def test_store_document_requires_editor_role():
    client = _make_client(role=Role.VIEWER)

    response = client.post(
        "/api/v1/knowledge/store?workspace_id=ws-test",
        json={"content": "x"},
    )

    assert response.status_code == 403
