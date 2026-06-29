"""Tests for per-user API key management endpoints."""

from __future__ import annotations

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
        METRONIX_OPENAI_COMPAT_KEY="test-static-key",
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
        email="admin@test.local",
        password="admin12345",
        role="admin",
        workspace_ids=["ws1"],
    )
    token = create_token(
        user_id=admin["id"],
        role="admin",
        workspace_ids=["ws1"],
        secret_key="test-secret",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        c.admin_user_id = admin["id"]
        yield c


@pytest.mark.asyncio
async def test_create_api_key(client):
    resp = await client.post(f"/api/v1/users/{client.admin_user_id}/api-keys")
    assert resp.status_code == 201
    data = resp.json()
    assert "raw_key" in data
    assert data["raw_key"].startswith("mtk_")


@pytest.mark.asyncio
async def test_list_api_keys(client):
    await client.post(f"/api/v1/users/{client.admin_user_id}/api-keys")
    resp = await client.get(f"/api/v1/users/{client.admin_user_id}/api-keys")
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) >= 1
    assert "raw_key" not in keys[0]


@pytest.mark.asyncio
async def test_revoke_api_key(client):
    create_resp = await client.post(f"/api/v1/users/{client.admin_user_id}/api-keys")
    raw_key = create_resp.json()["raw_key"]
    prefix = raw_key[:12]
    resp = await client.delete(f"/api/v1/users/{client.admin_user_id}/api-keys/{prefix}")
    assert resp.status_code == 204
