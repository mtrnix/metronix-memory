"""Tests for the /api/v1/upload backward-compat alias (delegates to _ingest_uploads)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.auth.dependencies import get_current_user
from metronix.auth.jwt import create_token
from metronix.core.config import Settings
from metronix.core.models import Role, User

_SECRET = "test-secret-for-upload-alias"


def _make_admin() -> User:
    return User(
        id="u_uploader",
        username="uploader",
        email="up@example.com",
        role=Role.ADMIN,
        workspace_ids=["default"],
    )


def _admin_token() -> str:
    return create_token(
        user_id="u_uploader",
        role="admin",
        workspace_ids=["default"],
        secret_key=_SECRET,
    )


@pytest.fixture
def client(monkeypatch):
    import metronix.api.routes.files as files_mod

    class _StubStore:
        async def upsert_raw_documents(self, **kw):
            return {
                "new": 1,
                "updated": 0,
                "unchanged": 0,
                "changed_source_ids": [d.source_id for d in kw["documents"]],
            }

        async def close(self) -> None:
            pass

    monkeypatch.setattr(files_mod, "PostgresStore", lambda *a, **k: _StubStore())

    async def fake_persist(store, ws, ct, conn_id, docs):
        return {
            "new": len(docs),
            "updated": 0,
            "unchanged": 0,
            "changed_source_ids": [d.source_id for d in docs],
        }

    async def fake_sync(store, ws, ct, docs, *, source_role, incremental):
        return None

    monkeypatch.setattr(files_mod, "persist_raw_documents", fake_persist)
    monkeypatch.setattr(files_mod, "sync_documents_to_stores", fake_sync)

    app = create_app(Settings(auth_enabled=False, METRONIX_SECRET_KEY=_SECRET))
    app.dependency_overrides[get_current_user] = _make_admin
    return TestClient(app, headers={"Authorization": f"Bearer {_admin_token()}"})


def test_legacy_upload_alias_still_ingests(client):
    resp = client.post(
        "/api/v1/upload",
        files={"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code in (200, 207)
    body = resp.json()
    assert body["accepted"] == 1
    assert body["results"][0]["source_id"] == "doc.txt"
