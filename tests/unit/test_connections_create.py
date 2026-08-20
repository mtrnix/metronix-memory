"""Tests for POST /api/v1/connections/ endpoint — connector-type aliasing."""

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


def _make_token(role: str = "admin", workspace_ids: list[str] | None = None) -> str:
    from metronix.auth.jwt import create_token

    return create_token(
        user_id="testuser",
        role=role,
        workspace_ids=workspace_ids or ["ws_test"],
        secret_key="test-secret",
    )


def _created_row(connector_type: str) -> dict:
    return {
        "id": "conn_gdrive_1",
        "workspace_id": "ws_test",
        "connector_type": connector_type,
        "name": "Team Drive",
        "config": {"credentials_json": "***"},
        "status": "active",
        "enabled": True,
        "error_message": None,
        "last_synced_at": None,
        "created_at": "2026-08-17T00:00:00+00:00",
        "updated_at": None,
        "sync_cron": "0 3 * * *",
        "next_run_at": None,
    }


class TestCreateConnectionConnectorTypeAlias:
    """POST /api/v1/connections/ resolves google_drive to the canonical gdrive."""

    @patch("metronix.api.routes.connections.ensure_workspace_exists", new_callable=AsyncMock)
    @patch("metronix.api.routes.connections._get_store")
    def test_google_drive_alias_stores_as_gdrive(
        self, mock_store, mock_ensure_ws, client: TestClient
    ) -> None:
        store = mock_store.return_value
        store.create_connection = AsyncMock(return_value=_created_row("gdrive"))
        store.set_connection_schedule = AsyncMock()

        token = _make_token()
        body = {
            "connector_type": "google_drive",
            "name": "Team Drive",
            "config": {"credentials_json": "{}"},
        }
        r = client.post(
            "/api/v1/connections/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

        assert r.status_code == 201, r.text
        assert r.json()["connector_type"] == "gdrive"

        # The alias must never reach the store — only the canonical name is
        # persisted, so existing `gdrive` rows and code paths are unaffected.
        forwarded_type = store.create_connection.await_args.kwargs["connector_type"]
        assert forwarded_type == "gdrive"

    @patch("metronix.api.routes.connections.ensure_workspace_exists", new_callable=AsyncMock)
    @patch("metronix.api.routes.connections._get_store")
    def test_canonical_gdrive_still_works(
        self, mock_store, mock_ensure_ws, client: TestClient
    ) -> None:
        store = mock_store.return_value
        store.create_connection = AsyncMock(return_value=_created_row("gdrive"))
        store.set_connection_schedule = AsyncMock()

        token = _make_token()
        body = {
            "connector_type": "gdrive",
            "name": "Team Drive",
            "config": {"credentials_json": "{}"},
        }
        r = client.post(
            "/api/v1/connections/?workspace_id=ws_test",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

        assert r.status_code == 201, r.text
        assert r.json()["connector_type"] == "gdrive"
