"""Regression tests for personal API-key authentication on /api/v1 routes."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.api.middleware import OptionalAuthMiddleware
from metronix.auth.api_key_store import ApiKeyStore
from metronix.auth.dependencies import get_current_user
from metronix.auth.user_store import UserStore
from metronix.core.config import Settings
from metronix.core.models import User


@pytest.fixture
async def client() -> TestClient:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    user_store = UserStore(engine)
    await user_store.ensure_schema()
    api_key_store = ApiKeyStore(engine)
    await api_key_store.ensure_schema()

    owner = await user_store.create_user(
        email="viewer@test.local",
        password="viewer-password",
        role="viewer",
        workspace_ids=["owner-workspace"],
    )
    owner_key = await api_key_store.create_key(owner["id"], label="hermes")

    app = FastAPI()
    app.state.settings = Settings(AUTH_ENABLED=True, METRONIX_SECRET_KEY="test-secret-key")
    app.state.user_store = user_store
    app.state.api_key_store = api_key_store
    app.add_middleware(OptionalAuthMiddleware)

    @app.get("/api/v1/protected")
    async def protected(user: User = Depends(get_current_user)) -> dict[str, object]:
        return {"role": user.role.value, "workspace_ids": user.workspace_ids}

    with TestClient(app) as test_client:
        test_client.owner_key = owner_key
        yield test_client

    await engine.dispose()


def test_personal_key_authenticates_protected_route(client: TestClient) -> None:
    response = client.get(
        "/api/v1/protected",
        headers={"Authorization": f"Bearer {client.owner_key}"},
    )

    assert response.status_code == 200
    assert response.json() == {"role": "viewer", "workspace_ids": ["owner-workspace"]}


def test_unknown_personal_key_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/protected",
        headers={"Authorization": "Bearer mtk_unknown"},
    )

    assert response.status_code == 401
