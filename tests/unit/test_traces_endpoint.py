"""Endpoint tests for the RAG debug trace read API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.routes.traces import router as traces_router
from metatron.auth.dependencies import get_current_user
from metatron.core.config import Settings
from metatron.core.models import Role, User


def _make_user() -> User:
    return User(
        id="u1",
        username="tester",
        email="t@example.com",
        role=Role.VIEWER,
        workspace_ids=["ws-test"],
    )


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(AUTH_ENABLED=False)
    app.include_router(traces_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _make_user
    return TestClient(app, raise_server_exceptions=False)


_UUID = "11111111-1111-1111-1111-111111111111"


def test_get_trace_returns_payload(client):
    payload = {"trace_id": _UUID, "phases": [], "input": {"raw_user_message": "hi"}}
    with patch("metatron.storage.pg_connection.get_rag_trace_sync", return_value=payload):
        resp = client.get(f"/api/v1/traces/{_UUID}")
    assert resp.status_code == 200
    assert resp.json()["trace_id"] == _UUID


def test_get_trace_unknown_is_404(client):
    # A well-formed but unknown UUID resolves to None in the store -> 404.
    with patch("metatron.storage.pg_connection.get_rag_trace_sync", return_value=None):
        resp = client.get("/api/v1/traces/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_get_trace_malformed_uuid_is_422(client):
    # Non-UUID path param is rejected by FastAPI validation, not a 500 from PG.
    resp = client.get("/api/v1/traces/not-a-uuid")
    assert resp.status_code == 422


def test_get_trace_works_when_capture_disabled(client):
    # Reads are NOT gated by the capture flag.
    payload = {"trace_id": _UUID, "phases": []}
    with patch("metatron.storage.pg_connection.get_rag_trace_sync", return_value=payload):
        resp = client.get(f"/api/v1/traces/{_UUID}")
    assert resp.status_code == 200


def test_get_trace_queries_auth_resolved_workspace(client):
    """Isolation contract: the route passes the auth-resolved workspace to the store,
    not a client-supplied one — so a trace id is only ever read within the caller's
    workspace (cross-workspace ids resolve to None → 404 in the store)."""
    expected_ws = client.app.state.settings.default_workspace_id
    mock = MagicMock(return_value={"trace_id": _UUID, "phases": []})
    with patch("metatron.storage.pg_connection.get_rag_trace_sync", mock):
        client.get(f"/api/v1/traces/{_UUID}")
    assert mock.call_args.args[0] == expected_ws
    assert mock.call_args.args[1] == _UUID


def test_list_traces_shape(client):
    rows = [
        {
            "trace_id": "t-1",
            "created_at": "2026-06-02T00:00:00+00:00",
            "query": "q",
            "source": "oai_compat",
            "total_ms": 12.0,
        }
    ]
    # Trailing slash is the registered path (redirect_slashes=False; the ui-cc
    # nginx rewrites bare /api/v1/traces to /api/v1/traces/ — repo convention).
    with patch("metatron.storage.pg_connection.list_rag_traces_sync", return_value=rows):
        resp = client.get("/api/v1/traces/?limit=5&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["traces"][0]["trace_id"] == "t-1"
    assert body["limit"] == 5
