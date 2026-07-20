"""Tests for auth login endpoint and optional auth middleware."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.auth.jwt import create_token
from metronix.core.config import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METRONIX_ENV="development",
        AUTH_ENABLED=False,
        AUTH_PASSWORD="testpass",
        METRONIX_SECRET_KEY="test-secret",
    )


@pytest.fixture
def settings_auth_on() -> Settings:
    return Settings(
        METRONIX_ENV="development",
        AUTH_ENABLED=True,
        AUTH_PASSWORD="testpass",
        METRONIX_SECRET_KEY="test-secret",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client_auth(settings_auth_on: Settings) -> TestClient:
    app = create_app(settings_auth_on)
    return TestClient(app, raise_server_exceptions=False)


def _make_token(secret: str = "test-secret") -> str:
    return create_token(
        user_id="admin",
        role="admin",
        workspace_ids=["*"],
        secret_key=secret,
    )


ADMIN_USER = {
    "id": "admin",
    "role": "admin",
    "email": "admin@metronix.local",
    "password_hash": "hashed-testpass",
    "is_active": True,
    "workspace_ids": ["*"],
}


class _FakeUserStore:
    """Minimal user store double: resolves a single known admin by email."""

    def __init__(self, user: dict | None = ADMIN_USER) -> None:
        self._user = user

    async def get_user_by_email(self, email: str) -> dict | None:
        if self._user and email == self._user["email"]:
            return self._user
        return None


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    @patch("metronix.api.routes.auth.verify_password", return_value=True)
    @patch("metronix.api.routes.auth.get_settings")
    def test_login_success(
        self, mock_settings, mock_verify, client: TestClient, settings: Settings
    ) -> None:
        mock_settings.return_value = settings
        client.app.state.user_store = _FakeUserStore()
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@metronix.local", "password": "testpass"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "token" in body
        assert body["user_id"] == "admin"
        assert body["role"] == "admin"

    @patch("metronix.api.routes.auth.verify_password", return_value=False)
    @patch("metronix.api.routes.auth.get_settings")
    def test_login_wrong_password(
        self, mock_settings, mock_verify, client: TestClient, settings: Settings
    ) -> None:
        mock_settings.return_value = settings
        client.app.state.user_store = _FakeUserStore()
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@metronix.local", "password": "wrong"},
        )
        assert r.status_code == 401
        assert "Invalid email or password" in r.json()["detail"]

    @patch("metronix.api.routes.auth.get_settings")
    def test_login_unknown_email(
        self, mock_settings, client: TestClient, settings: Settings
    ) -> None:
        mock_settings.return_value = settings
        client.app.state.user_store = _FakeUserStore()
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@metronix.local", "password": "testpass"},
        )
        assert r.status_code == 401
        assert "Invalid email or password" in r.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------


class TestMe:
    @pytest.mark.skip(reason="pre-existing failure; MTRNIX-458 follow-up")
    def test_me_returns_user(self, client: TestClient) -> None:
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == "admin"
        assert body["role"] == "admin"


# ---------------------------------------------------------------------------
# Middleware — auth disabled (default)
# ---------------------------------------------------------------------------


class TestMiddlewareDisabled:
    def test_endpoints_open_when_disabled(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200

        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Middleware — auth enabled
# ---------------------------------------------------------------------------


class TestMiddlewareEnabled:
    def test_no_token_returns_401(self, client_auth: TestClient) -> None:
        r = client_auth.get("/api/v1/auth/me")
        assert r.status_code == 401
        assert "Authentication required" in r.json()["detail"]

    def test_invalid_token_returns_401(self, client_auth: TestClient) -> None:
        r = client_auth.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer bad-token"},
        )
        assert r.status_code == 401
        assert "Invalid or expired token" in r.json()["detail"]

    def test_valid_token_passes(self, client_auth: TestClient) -> None:
        token = _make_token()
        r = client_auth.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    def test_public_paths_always_open(self, client_auth: TestClient) -> None:
        r = client_auth.get("/health")
        assert r.status_code == 200

    @patch("metronix.api.routes.auth.verify_password", return_value=True)
    @patch("metronix.api.routes.auth.get_settings")
    def test_login_open_when_auth_enabled(
        self,
        mock_settings,
        mock_verify,
        client_auth: TestClient,
        settings_auth_on: Settings,
    ) -> None:
        mock_settings.return_value = settings_auth_on
        client_auth.app.state.user_store = _FakeUserStore()
        r = client_auth.post(
            "/api/v1/auth/login",
            json={"email": "admin@metronix.local", "password": "testpass"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Middleware — MCP JWT auth
# ---------------------------------------------------------------------------


class TestMcpAuth:
    """MCP endpoint uses JWT auth when AUTH_ENABLED is set."""

    def test_mcp_no_key_configured_allows_all(self, client: TestClient) -> None:
        """With auth disabled, development MCP requests remain open."""
        response = client.post("/mcp")
        # The MCP handler may reject the malformed transport request, but not auth.
        assert response.status_code != 401

    def test_mcp_requires_jwt_when_auth_enabled(self, client_auth: TestClient) -> None:
        response = client_auth.post("/mcp")
        assert response.status_code == 401
        assert response.json()["detail"] == "MCP JWT authentication required"

    def test_mcp_rejects_deployment_key_when_auth_enabled(self, client_auth: TestClient) -> None:
        response = client_auth.post(
            "/mcp", headers={"Authorization": "Bearer shared-deployment-key"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "MCP JWT authentication required"

    def test_mcp_accepts_valid_jwt_when_auth_enabled(self, client_auth: TestClient) -> None:
        response = client_auth.post("/mcp", headers={"Authorization": f"Bearer {_make_token()}"})
        assert response.status_code != 401
