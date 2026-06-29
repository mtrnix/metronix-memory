"""Tests for Open WebUI sync on user CRUD."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from metronix.auth.openwebui_sync import OpenWebUISync


@pytest.fixture
def sync_service():
    svc = OpenWebUISync(
        owui_url="http://owui:8080",
        metronix_url="http://metronix:8000/v1",
        admin_email="admin@metronix.local",
        admin_password="metronix",
    )
    svc._client.login = AsyncMock(return_value={"token": "admin-jwt"})
    svc._client._admin_token = "admin-jwt"
    return svc


@pytest.mark.asyncio
async def test_sync_create_user(sync_service):
    sync_service._client.create_user = AsyncMock(
        return_value={
            "id": "owui-1",
            "token": "user-jwt",
        }
    )
    sync_service._client.set_direct_connection = AsyncMock()

    result = await sync_service.sync_user_created(
        email="new@test.local",
        name="New User",
        password="pass123",
        role="viewer",
        api_key="mtk_abc",
    )

    sync_service._client.create_user.assert_called_once_with(
        name="New User",
        email="new@test.local",
        password="pass123",
        role="user",
    )
    sync_service._client.set_direct_connection.assert_called_once_with(
        user_token="user-jwt",
        metronix_url="http://metronix:8000/v1",
        api_key="mtk_abc",
    )
    assert result["owui_user_id"] == "owui-1"


@pytest.mark.asyncio
async def test_sync_disabled_when_no_url():
    svc = OpenWebUISync(owui_url="", metronix_url="")
    result = await svc.sync_user_created(
        email="x@test.local",
        name="X",
        password="p",
        role="viewer",
        api_key="k",
    )
    assert result is None
    assert svc.enabled is False


@pytest.mark.asyncio
async def test_role_mapping(sync_service):
    assert sync_service._map_role_to_owui("admin") == "admin"
    assert sync_service._map_role_to_owui("editor") == "user"
    assert sync_service._map_role_to_owui("viewer") == "user"


@pytest.mark.asyncio
async def test_sync_user_updated(sync_service):
    sync_service._client.update_user = AsyncMock(return_value={})
    result = await sync_service.sync_user_updated(
        owui_user_id="owui-1",
        name="Updated",
        email="u@test.local",
        role="admin",
    )
    assert result is True
    sync_service._client.update_user.assert_called_once()


@pytest.mark.asyncio
async def test_sync_user_deleted(sync_service):
    sync_service._client.delete_user = AsyncMock(return_value=True)
    result = await sync_service.sync_user_deleted(owui_user_id="owui-1")
    assert result is True
    sync_service._client.delete_user.assert_called_once_with("owui-1")


@pytest.mark.asyncio
async def test_ensure_admin_signin(sync_service):
    """If signin works, no signup needed."""
    sync_service._client.login = AsyncMock(return_value={"token": "jwt"})
    sync_service._client.signup = AsyncMock()
    await sync_service.ensure_admin()
    sync_service._client.login.assert_called_once()
    sync_service._client.signup.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_admin_signup_fallback(sync_service):
    """If signin fails, try signup."""
    sync_service._client.login = AsyncMock(side_effect=Exception("401"))
    sync_service._client.signup = AsyncMock(return_value={"token": "jwt"})
    await sync_service.ensure_admin()
    sync_service._client.signup.assert_called_once()
