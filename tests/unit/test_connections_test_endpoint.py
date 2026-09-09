"""Tests for POST /api/v1/connections/{id}/test/ — configure + health_check."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from metronix.api.app import create_app
from metronix.core.config import Settings

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


def _make_token(role: str = "admin", workspace_ids: list[str] | None = None) -> str:
    from metronix.auth.jwt import create_token

    return create_token(
        user_id="testuser",
        role=role,
        workspace_ids=workspace_ids or ["ws_test"],
        secret_key="test-secret",
    )


_DECRYPTED_CONFLUENCE = {
    "id": "conn_conf_1",
    "workspace_id": "ws_test",
    "connector_type": "confluence",
    "name": "Confluence",
    "config": {
        "url": "https://acme.atlassian.net/wiki",
        "username": "bot@acme.com",
        "api_token": "super-secret-token",
        "space_key": "ENG",
    },
    "status": "pending",
    "enabled": True,
    "error_message": None,
    "last_synced_at": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": None,
}


def _mock_registry(*, health: bool = True, configure_exc: Exception | None = None):
    """Build a fake connector registry + connector for the test endpoint."""
    connector = MagicMock()
    if configure_exc is not None:
        connector.configure = AsyncMock(side_effect=configure_exc)
    else:
        connector.configure = AsyncMock(return_value=None)
    connector.health_check = AsyncMock(return_value=health)

    registry = MagicMock()
    registry.is_registered.return_value = True
    registry.create.return_value = connector
    return registry, connector


class TestConnectionTestEndpoint:
    """POST /api/v1/connections/{id}/test/ runs configure + health_check."""

    @patch("metronix.api.routes.connections.get_registry")
    @patch("metronix.api.routes.connections._get_store")
    def test_health_check_true_marks_active(
        self, mock_store, mock_get_registry, client: TestClient
    ) -> None:
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=_DECRYPTED_CONFLUENCE)
        store.update_connection_status = AsyncMock()

        registry, connector = _mock_registry(health=True)
        mock_get_registry.return_value = registry

        token = _make_token()
        r = client.post(
            "/api/v1/connections/conn_conf_1/test/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body.get("error") is None

        connector.configure.assert_awaited_once()
        connector.health_check.assert_awaited_once()
        store.update_connection_status.assert_awaited_once_with(
            "conn_conf_1",
            status="active",
            error_message=None,
        )

    @patch("metronix.api.routes.connections.get_registry")
    @patch("metronix.api.routes.connections._get_store")
    def test_health_check_false_marks_error(
        self, mock_store, mock_get_registry, client: TestClient
    ) -> None:
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=_DECRYPTED_CONFLUENCE)
        store.update_connection_status = AsyncMock()

        registry, connector = _mock_registry(health=False)
        mock_get_registry.return_value = registry

        token = _make_token()
        r = client.post(
            "/api/v1/connections/conn_conf_1/test/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is False
        assert body["error"]
        assert "Health check failed" in body["error"]

        connector.configure.assert_awaited_once()
        connector.health_check.assert_awaited_once()
        store.update_connection_status.assert_awaited_once_with(
            "conn_conf_1",
            status="error",
            error_message=body["error"],
        )

    @patch("metronix.api.routes.connections.get_registry")
    @patch("metronix.api.routes.connections._get_store")
    def test_configure_raises_marks_error(
        self, mock_store, mock_get_registry, client: TestClient
    ) -> None:
        store = mock_store.return_value
        store.get_connection_decrypted = AsyncMock(return_value=_DECRYPTED_CONFLUENCE)
        store.update_connection_status = AsyncMock()

        registry, connector = _mock_registry(
            configure_exc=ValueError("invalid credentials blob"),
        )
        mock_get_registry.return_value = registry

        token = _make_token()
        r = client.post(
            "/api/v1/connections/conn_conf_1/test/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is False
        assert "invalid credentials blob" in body["error"]

        connector.configure.assert_awaited_once()
        connector.health_check.assert_not_awaited()
        store.update_connection_status.assert_awaited_once_with(
            "conn_conf_1",
            status="error",
            error_message=body["error"],
        )
