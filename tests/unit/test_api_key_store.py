"""Tests for personal API key store."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.auth.api_key_store import ApiKeyStore


@pytest.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    s = ApiKeyStore(engine)
    await s.ensure_schema()
    return s


@pytest.mark.asyncio
async def test_create_and_verify(store):
    raw_key = await store.create_key(user_id="user-1", label="default")
    assert raw_key.startswith("mtk_")
    resolved = await store.resolve_key(raw_key)
    assert resolved is not None
    assert resolved["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_resolve_invalid_key(store):
    resolved = await store.resolve_key("mtk_nonexistent")
    assert resolved is None


@pytest.mark.asyncio
async def test_list_keys(store):
    await store.create_key(user_id="user-1", label="key-a")
    await store.create_key(user_id="user-1", label="key-b")
    keys = await store.list_keys(user_id="user-1")
    assert len(keys) == 2
    assert "key_hash" not in keys[0]


@pytest.mark.asyncio
async def test_revoke_key(store):
    raw_key = await store.create_key(user_id="user-1", label="temp")
    revoked = await store.revoke_key(key_prefix=raw_key[:12], user_id="user-1")
    assert revoked is True
    assert await store.resolve_key(raw_key) is None


@pytest.mark.asyncio
async def test_revoke_nonexistent(store):
    revoked = await store.revoke_key(key_prefix="mtk_xxxxxxx", user_id="user-1")
    assert revoked is False


@pytest.mark.asyncio
async def test_static_key_fallback(store):
    """When a static key is configured, resolve_key should check it too."""
    resolved = await store.resolve_key("static-key-123", static_key="static-key-123")
    assert resolved is not None
    assert resolved["user_id"] == "openai-default"
