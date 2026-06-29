"""Tests for GET /api/v1/connections/{id}/reveal-secrets/ endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.core.config import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FERNET_KEY = "dGVzdC1mZXJuZXQta2V5LTMyLWJ5dGVzLWxvbmc="  # 32-byte base64


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METRONIX_ENV="development",
        AUTH_ENABLED=True,
        AUTH_PASSWORD="testpass",
        METRONIX_SECRET_KEY="test-secret",
        FERNET_KEY=_FERNET_KEY,
        DEFAULT_WORKSPACE_ID="ws_test",
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _make_token(
    role: str = "admin",
    workspace_ids: list[str] | None = None,
    secret: str = "test-secret",
) -> str:
    from metronix.auth.jwt import create_token

    return create_token(
        user_id="testuser",
        role=role,
        workspace_ids=workspace_ids or ["ws_test"],
        secret_key=secret,
    )


_DECRYPTED_CONN = {
    "id": "conn_001",
    "workspace_id": "ws_test",
    "connector_type": "jira",
    "name": "Jira",
    "config": {
        "url": "https://acme.atlassian.net/",
        "username": "bot@acme.com",
        "api_token": "super-secret-token-123",
        "project_key": "PROJ",
    },
    "status": "active",
    "enabled": True,
    "error_message": None,
    "last_synced_at": None,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": None,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRevealSecrets:
    """GET /api/v1/connections/{id}/reveal-secrets/."""

    @patch("metronix.api.routes.connections._get_store")
    def test_admin_can_reveal(self, mock_store, client: TestClient) -> None:
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=_DECRYPTED_CONN)

        token = _make_token(role="admin")
        r = client.get(
            "/api/v1/connections/conn_001/reveal-secrets/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200
        body = r.json()
        assert body["config"]["api_token"] == "super-secret-token-123"
        assert body["id"] == "conn_001"

    @patch("metronix.api.routes.connections._get_store")
    def test_editor_can_reveal(self, mock_store, client: TestClient) -> None:
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=_DECRYPTED_CONN)

        token = _make_token(role="editor")
        r = client.get(
            "/api/v1/connections/conn_001/reveal-secrets/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200
        assert r.json()["config"]["api_token"] == "super-secret-token-123"

    def test_viewer_gets_403(self, client: TestClient) -> None:
        token = _make_token(role="viewer")
        r = client.get(
            "/api/v1/connections/conn_001/reveal-secrets/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 403
        assert "Editor access required" in r.json()["detail"]

    def test_no_auth_gets_401(self, client: TestClient) -> None:
        r = client.get(
            "/api/v1/connections/conn_001/reveal-secrets/?workspace_id=ws_test",
        )

        assert r.status_code == 401

    @patch("metronix.api.routes.connections._get_store")
    def test_not_found_returns_404(self, mock_store, client: TestClient) -> None:
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=None)

        token = _make_token(role="admin")
        r = client.get(
            "/api/v1/connections/nonexistent/reveal-secrets/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 404

    @patch("metronix.api.routes.connections._get_store")
    def test_wrong_workspace_returns_404(self, mock_store, client: TestClient) -> None:
        conn = {**_DECRYPTED_CONN, "workspace_id": "other_ws"}
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=conn)

        token = _make_token(role="admin")
        r = client.get(
            "/api/v1/connections/conn_001/reveal-secrets/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 404


class TestRevealSecretsAuthDisabled:
    """reveal-secrets when AUTH_ENABLED=false (no role in request.state.user)."""

    @pytest.fixture
    def client_no_auth(self) -> TestClient:
        settings = Settings(
            METRONIX_ENV="development",
            AUTH_ENABLED=False,
            FERNET_KEY=_FERNET_KEY,
            DEFAULT_WORKSPACE_ID="ws_test",
        )
        app = create_app(settings)
        return TestClient(app, raise_server_exceptions=False)

    @patch("metronix.api.routes.connections._get_store")
    def test_reveal_works_without_auth(self, mock_store, client_no_auth: TestClient) -> None:
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=_DECRYPTED_CONN)

        r = client_no_auth.get(
            "/api/v1/connections/conn_001/reveal-secrets/?workspace_id=ws_test",
        )

        assert r.status_code == 200
        assert r.json()["config"]["api_token"] == "super-secret-token-123"
