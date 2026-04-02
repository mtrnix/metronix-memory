"""Tests for auth login endpoint and optional auth middleware."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.auth.jwt import create_token
from metatron.core.config import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=False,
        AUTH_PASSWORD="testpass",
        METATRON_SECRET_KEY="test-secret",
    )


@pytest.fixture
def settings_auth_on() -> Settings:
    return Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=True,
        AUTH_PASSWORD="testpass",
        METATRON_SECRET_KEY="test-secret",
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


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    @patch("metatron.api.routes.auth.get_settings")
    def test_login_success(self, mock_settings, client: TestClient, settings: Settings) -> None:
        mock_settings.return_value = settings
        r = client.post("/api/v1/auth/login", json={"password": "testpass"})
        assert r.status_code == 200
        body = r.json()
        assert "token" in body
        assert body["user_id"] == "admin"
        assert body["role"] == "admin"

    @patch("metatron.api.routes.auth.get_settings")
    def test_login_wrong_password(
        self, mock_settings, client: TestClient, settings: Settings
    ) -> None:
        mock_settings.return_value = settings
        r = client.post("/api/v1/auth/login", json={"password": "wrong"})
        assert r.status_code == 401
        assert "Invalid password" in r.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------


class TestMe:
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

    @patch("metatron.api.routes.auth.get_settings")
    def test_login_open_when_auth_enabled(
        self,
        mock_settings,
        client_auth: TestClient,
        settings_auth_on: Settings,
    ) -> None:
        mock_settings.return_value = settings_auth_on
        r = client_auth.post("/api/v1/auth/login", json={"password": "testpass"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Middleware — MCP API key auth (independent of AUTH_ENABLED)
# ---------------------------------------------------------------------------


class TestMcpAuth:
    """MCP endpoint uses METATRON_MCP_API_KEY, not JWT, regardless of AUTH_ENABLED."""

    def test_mcp_no_key_configured_allows_all(self, client: TestClient) -> None:
        """When METATRON_MCP_API_KEY is not set, /mcp is open (dev mode)."""
        with patch("metatron.api.middleware.validate_api_key", return_value=True):
            r = client.post("/mcp")
            # MCP handler may return an error (no valid MCP request), but not 401
            assert r.status_code != 401

    def test_mcp_rejects_without_key(self, client: TestClient) -> None:
        """When METATRON_MCP_API_KEY is set, /mcp rejects requests without key."""
        with patch("metatron.api.middleware.validate_api_key", return_value=False):
            r = client.post("/mcp")
            assert r.status_code == 401
            assert "MCP API key" in r.json()["error"]

    def test_mcp_rejects_wrong_key(self, client: TestClient) -> None:
        """When METATRON_MCP_API_KEY is set, /mcp rejects wrong key."""
        with patch("metatron.api.middleware.validate_api_key", return_value=False):
            r = client.post("/mcp", headers={"Authorization": "Bearer wrong"})
            assert r.status_code == 401

    def test_mcp_accepts_correct_key(self, client: TestClient) -> None:
        """When correct key is provided, /mcp passes through."""
        with patch("metatron.api.middleware.validate_api_key", return_value=True):
            r = client.post("/mcp")
            assert r.status_code != 401

    def test_mcp_auth_works_with_auth_enabled(self, client_auth: TestClient) -> None:
        """MCP uses API key auth even when AUTH_ENABLED=true (not JWT)."""
        with patch("metatron.api.middleware.validate_api_key", return_value=True):
            r = client_auth.post("/mcp")
            # Should not get JWT 401
            assert r.status_code != 401

    def test_mcp_rejects_with_auth_enabled(self, client_auth: TestClient) -> None:
        """MCP rejects bad key even when AUTH_ENABLED=true."""
        with patch("metatron.api.middleware.validate_api_key", return_value=False):
            r = client_auth.post("/mcp")
            assert r.status_code == 401
            assert "MCP API key" in r.json()["error"]
