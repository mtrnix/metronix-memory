"""Tests for Open WebUI API client."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from metronix.auth.openwebui_client import OpenWebUIClient


@pytest.fixture
def owui():
    return OpenWebUIClient(base_url="http://owui:8080")


@respx.mock
@pytest.mark.asyncio
async def test_login(owui):
    respx.post("http://owui:8080/api/v1/auths/signin").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "admin-1",
                "token": "jwt-admin",
                "role": "admin",
            },
        )
    )
    result = await owui.login("admin@test.local", "pass")
    assert result["token"] == "jwt-admin"
    assert owui._admin_token == "jwt-admin"


@respx.mock
@pytest.mark.asyncio
async def test_list_users(owui):
    owui._admin_token = "jwt-admin"
    respx.get("http://owui:8080/api/v1/users/").mock(
        return_value=httpx.Response(
            200,
            json={
                "users": [
                    {"id": "u1", "email": "a@test.local", "name": "A", "role": "admin"},
                    {"id": "u2", "email": "b@test.local", "name": "B", "role": "user"},
                ],
                "total": 2,
            },
        )
    )
    users = await owui.list_users()
    assert len(users) == 2


@respx.mock
@pytest.mark.asyncio
async def test_create_user(owui):
    owui._admin_token = "jwt-admin"
    respx.post("http://owui:8080/api/v1/auths/add").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "u3",
                "email": "c@test.local",
                "name": "C",
                "role": "user",
                "token": "jwt-u3",
            },
        )
    )
    result = await owui.create_user("C", "c@test.local", "pass123", "user")
    assert result["token"] == "jwt-u3"


@respx.mock
@pytest.mark.asyncio
async def test_set_direct_connection(owui):
    respx.post("http://owui:8080/api/v1/users/user/settings/update").mock(
        return_value=httpx.Response(200, json={"ui": {"directConnections": {}}})
    )
    await owui.set_direct_connection(
        user_token="jwt-u3",
        metronix_url="http://metronix:8000/v1",
        api_key="mtk_abc123",
    )
    req = respx.calls.last.request
    assert req.headers["authorization"] == "Bearer jwt-u3"
    body = json.loads(req.content)
    assert body["ui"]["directConnections"]["OPENAI_API_KEYS"] == ["mtk_abc123"]


@respx.mock
@pytest.mark.asyncio
async def test_delete_user(owui):
    owui._admin_token = "jwt-admin"
    respx.delete("http://owui:8080/api/v1/users/u3").mock(
        return_value=httpx.Response(200, text="true")
    )
    result = await owui.delete_user("u3")
    assert result is True
