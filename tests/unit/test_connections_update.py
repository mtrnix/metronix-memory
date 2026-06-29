"""Tests for PUT /api/v1/connections/{id}/ endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


_EXISTING_JIRA = {
    "id": "conn_001",
    "workspace_id": "ws_test",
    "connector_type": "jira",
    "name": "Jira",
    "config": {
        "url": "https://acme.atlassian.net/",
        "username": "bot@acme.com",
        "api_token": "***",
        "project_key": "PROJ",
    },
    "status": "active",
    "enabled": True,
    "error_message": None,
    "last_synced_at": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": None,
}


def _updated_row(**overrides) -> dict:
    row = dict(_EXISTING_JIRA)
    row["updated_at"] = "2026-04-16T12:00:00+00:00"
    row.update(overrides)
    return row


class TestUpdateConnection:
    """PUT /api/v1/connections/{id}/."""

    @patch("metronix.api.routes.connections._get_store")
    def test_happy_path_with_masked_secret(self, mock_store, client: TestClient) -> None:
        """User saves form with api_token still '***' — update must succeed (200)."""
        store = mock_store.return_value
        store.get_connection = AsyncMock(return_value=_EXISTING_JIRA)
        store.update_connection = AsyncMock(
            return_value=_updated_row(name="Jira renamed"),
        )

        token = _make_token(role="admin")
        body = {
            "name": "Jira renamed",
            "config": {
                "url": "https://acme.atlassian.net/",
                "username": "bot@acme.com",
                "api_token": "***",
                "project_key": "PROJ",
            },
        }
        r = client.put(
            "/api/v1/connections/conn_001/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["name"] == "Jira renamed"
        assert payload["config"]["api_token"] == "***"  # still masked on response
        assert payload["updated_at"] == "2026-04-16T12:00:00+00:00"

        # Masked secret must be forwarded verbatim — merge_config unmasks it in the store.
        update_args = store.update_connection.await_args
        assert update_args is not None
        forwarded_updates = update_args.args[1]
        assert forwarded_updates["name"] == "Jira renamed"
        assert forwarded_updates["config"]["api_token"] == "***"

    @patch("metronix.api.routes.connections._get_store")
    def test_rotates_secret_when_real_value_sent(self, mock_store, client: TestClient) -> None:
        """Non-masked api_token is passed through to the store as-is."""
        store = mock_store.return_value
        store.get_connection = AsyncMock(return_value=_EXISTING_JIRA)
        store.update_connection = AsyncMock(return_value=_updated_row())

        token = _make_token(role="admin")
        body = {
            "config": {
                "url": "https://acme.atlassian.net/",
                "username": "bot@acme.com",
                "api_token": "fresh-token-xyz",
                "project_key": "PROJ",
            },
        }
        r = client.put(
            "/api/v1/connections/conn_001/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

        assert r.status_code == 200, r.text
        forwarded = store.update_connection.await_args.args[1]["config"]
        assert forwarded["api_token"] == "fresh-token-xyz"

    @patch("metronix.api.routes.connections._get_store")
    def test_missing_required_field_returns_422(self, mock_store, client: TestClient) -> None:
        """Removing a required non-secret field fails validation even if secret is masked."""
        store = mock_store.return_value
        store.get_connection = AsyncMock(return_value=_EXISTING_JIRA)
        store.update_connection = AsyncMock()

        token = _make_token(role="admin")
        # Drop required `url` while keeping the secret masked.
        body = {
            "config": {
                "username": "bot@acme.com",
                "api_token": "***",
                "project_key": "PROJ",
            },
        }
        r = client.put(
            "/api/v1/connections/conn_001/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

        assert r.status_code == 422
        assert "Jira URL" in r.json()["detail"]
        store.update_connection.assert_not_called()

    @patch("metronix.api.routes.connections._get_store")
    def test_wrong_workspace_returns_404(self, mock_store, client: TestClient) -> None:
        store = mock_store.return_value
        store.get_connection = AsyncMock(
            return_value={**_EXISTING_JIRA, "workspace_id": "other_ws"},
        )

        token = _make_token(role="admin")
        r = client.put(
            "/api/v1/connections/conn_001/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "renamed"},
        )

        assert r.status_code == 404

    @patch("metronix.api.routes.connections._get_store")
    def test_no_fields_to_update_returns_422(self, mock_store, client: TestClient) -> None:
        store = mock_store.return_value
        store.get_connection = AsyncMock(return_value=_EXISTING_JIRA)

        token = _make_token(role="admin")
        r = client.put(
            "/api/v1/connections/conn_001/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

        assert r.status_code == 422
        assert "No fields to update" in r.json()["detail"]
