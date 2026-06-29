"""Tests for Open WebUI user import endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.api.app import create_app
from metronix.auth.api_key_store import ApiKeyStore
from metronix.auth.user_store import UserStore
from metronix.core.config import Settings


@pytest.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    settings = Settings(
        METRONIX_ENV="development",
        METRONIX_SECRET_KEY="test-secret",
        AUTH_ENABLED=True,
        METRONIX_OPENAI_COMPAT_ENABLED=True,
        METRONIX_OPENAI_COMPAT_KEY="test-key",
    )
    app = create_app(settings)

    user_store = UserStore(engine)
    await user_store.ensure_schema()
    api_key_store = ApiKeyStore(engine)
    await api_key_store.ensure_schema()

    app.state.user_store = user_store
    app.state.api_key_store = api_key_store

    from metronix.auth.jwt import create_token

    admin = await user_store.create_user(
        email="admin@metronix.local",
        password="admin12345",
        role="admin",
    )
    token = create_token(
        user_id=admin["id"],
        role="admin",
        workspace_ids=[],
        secret_key="test-secret",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_import_users(client):
    mock_owui_users = [
        {"id": "u1", "email": "alice@ext.local", "name": "Alice", "role": "admin"},
        {"id": "u2", "email": "bob@ext.local", "name": "Bob", "role": "user"},
        {"id": "u3", "email": "pending@ext.local", "name": "Pending", "role": "pending"},
    ]

    with patch("metronix.api.routes.openwebui_import.OpenWebUIClient") as MockClient:  # noqa: N806
        instance = MockClient.return_value
        instance.login = AsyncMock(return_value={"token": "admin-jwt"})
        instance.list_users = AsyncMock(return_value=mock_owui_users)

        resp = await client.post(
            "/api/v1/admin/import-openwebui-users",
            json={
                "owui_url": "http://owui:8080",
                "admin_email": "admin@ext.local",
                "admin_password": "pass",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["imported"]) == 2
    assert data["skipped"] == 1
    alice = next(u for u in data["imported"] if u["email"] == "alice@ext.local")
    assert "metronix_password" in alice
    assert "api_key" in alice
    assert alice["api_key"].startswith("mtk_")
    assert alice["role"] == "admin"
    bob = next(u for u in data["imported"] if u["email"] == "bob@ext.local")
    assert bob["role"] == "viewer"


@pytest.mark.asyncio
async def test_import_skips_existing(client):
    mock_owui_users = [
        {"id": "u1", "email": "admin@metronix.local", "name": "Admin", "role": "admin"},
        {"id": "u2", "email": "new@ext.local", "name": "New", "role": "user"},
    ]

    with patch("metronix.api.routes.openwebui_import.OpenWebUIClient") as MockClient:  # noqa: N806
        instance = MockClient.return_value
        instance.login = AsyncMock(return_value={"token": "jwt"})
        instance.list_users = AsyncMock(return_value=mock_owui_users)

        resp = await client.post(
            "/api/v1/admin/import-openwebui-users",
            json={
                "owui_url": "http://owui:8080",
                "admin_email": "admin@ext.local",
                "admin_password": "pass",
            },
        )

    data = resp.json()
    assert len(data["imported"]) == 1
    assert data["already_existed"] == 1
