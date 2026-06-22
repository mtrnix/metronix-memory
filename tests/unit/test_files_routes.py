"""Tests for POST /api/v1/files/ (multipart upload endpoint)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.auth.dependencies import get_current_user
from metatron.auth.jwt import create_token
from metatron.core.config import Settings
from metatron.core.models import Role, User

_SECRET = "test-secret-for-files-routes"


def _make_editor() -> User:
    return User(
        id="u_uploader",
        username="uploader",
        email="up@example.com",
        role=Role.EDITOR,
        workspace_ids=["default"],
    )


def _editor_token() -> str:
    """Create a JWT editor token for the test secret."""
    return create_token(
        user_id="u_uploader",
        role="editor",
        workspace_ids=["default"],
        secret_key=_SECRET,
    )


@pytest.fixture
def client(monkeypatch):
    # Stub the shared ingestion layer so the test is hermetic (no DB/Qdrant).
    import metatron.api.routes.files as files_mod

    captured = {"persist": [], "sync": []}

    class _StubStore:
        async def upsert_raw_documents(self, **kw):
            return {"new": 1, "updated": 0, "unchanged": 0,
                    "changed_source_ids": [d.source_id for d in kw["documents"]]}

    monkeypatch.setattr(files_mod, "PostgresStore", lambda *a, **k: _StubStore())

    async def fake_persist(store, ws, ct, conn_id, docs):
        captured["persist"].append([d.source_id for d in docs])
        return {"new": len(docs), "updated": 0, "unchanged": 0,
                "changed_source_ids": [d.source_id for d in docs]}

    async def fake_sync(store, ws, ct, docs, *, source_role, incremental):
        captured["sync"].append([d.source_id for d in docs])

    monkeypatch.setattr(files_mod, "persist_raw_documents", fake_persist)
    monkeypatch.setattr(files_mod, "sync_documents_to_stores", fake_sync)

    # auth_enabled=False may be overridden to True by the enterprise plugin.
    # Pass a known secret key so we can issue a valid token unconditionally.
    app = create_app(Settings(auth_enabled=False, METATRON_SECRET_KEY=_SECRET))
    # Override get_current_user so require_editor resolves without DB lookup.
    app.dependency_overrides[get_current_user] = _make_editor
    c = TestClient(app, headers={"Authorization": f"Bearer {_editor_token()}"})
    c._captured = captured
    return c


def test_multipart_upload_mixed_report(client):
    files = [
        ("files", ("ok.txt", io.BytesIO(b"hello"), "text/plain")),
        ("files", ("bad.zip", io.BytesIO(b"PK\x03\x04"), "application/zip")),
        ("files", ("empty.txt", io.BytesIO(b"   "), "text/plain")),
    ]
    resp = client.post("/api/v1/files/", files=files)
    assert resp.status_code == 207
    body = resp.json()
    assert body["accepted"] == 1
    assert body["skipped"] == 2
    statuses = {r["filename"]: r["status"] for r in body["results"]}
    assert statuses["ok.txt"] == "accepted"
    assert statuses["bad.zip"] == "skipped_format"
    assert statuses["empty.txt"] == "skipped_empty"
    # Only the accepted doc reaches persistence.
    assert client._captured["persist"] == [["ok.txt"]]


def test_multipart_all_accepted_returns_200(client):
    files = [("files", ("a.txt", io.BytesIO(b"body"), "text/plain"))]
    resp = client.post("/api/v1/files/", files=files)
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 1
