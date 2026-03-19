"""Tests for auth/user_mapping.py — platform user mapping."""

from __future__ import annotations

import time
from typing import Any

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import create_async_engine

from metatron.auth.user_store import UserStore
from metatron.auth.user_mapping import PlatformUserMapper, _CACHE_TTL_SECONDS
from metatron.core.events import USER_CREATED
from metatron.core.models import User


class FakeEventBus:
    """Captures emitted events for assertions."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        self.emitted.append((event_name, payload))


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    await eng.dispose()


@pytest.fixture
async def user_store(engine):
    store = UserStore(engine)
    await store.ensure_schema()
    return store


@pytest.fixture
async def mapper(engine, user_store):
    m = PlatformUserMapper(engine, user_store)
    await m.ensure_schema()
    return m


@pytest.fixture
def event_bus():
    return FakeEventBus()


class TestMapPlatformUser:
    @pytest.mark.asyncio
    async def test_auto_create_new_user(self, mapper, event_bus):
        """Unknown platform user with auto_create=True creates viewer."""
        user = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="12345",
            workspace_id="ws_1",
            event_bus=event_bus,
            display_name="Ivan Petrov",
        )
        assert user is not None
        assert isinstance(user, User)
        assert user.role.value == "viewer"
        assert "ws_1" in user.workspace_ids

    @pytest.mark.asyncio
    async def test_auto_create_emits_event(self, mapper, event_bus):
        """Auto-create should emit USER_CREATED event."""
        await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="12345",
            workspace_id="ws_1",
            event_bus=event_bus,
            display_name="Ivan",
        )
        assert len(event_bus.emitted) == 1
        name, payload = event_bus.emitted[0]
        assert name == USER_CREATED
        assert payload["channel"] == "telegram"
        assert payload["channel_user_id"] == "12345"
        assert payload["auto_created"] is True
        assert payload["display_name"] == "Ivan"

    @pytest.mark.asyncio
    async def test_no_auto_create_returns_none(self, mapper, event_bus):
        """Unknown user with auto_create=False returns None."""
        user = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="99999",
            workspace_id="ws_1",
            event_bus=event_bus,
            auto_create=False,
        )
        assert user is None
        assert len(event_bus.emitted) == 0

    @pytest.mark.asyncio
    async def test_existing_user_returned(self, mapper, event_bus):
        """Second call for same platform user returns same internal user, no event."""
        user1 = await mapper.map_platform_user(
            channel="slack",
            channel_user_id="U001",
            workspace_id="ws_1",
            event_bus=event_bus,
            display_name="Alice",
        )
        event_bus.emitted.clear()

        user2 = await mapper.map_platform_user(
            channel="slack",
            channel_user_id="U001",
            workspace_id="ws_1",
            event_bus=event_bus,
        )
        assert user2 is not None
        assert user2.id == user1.id
        assert len(event_bus.emitted) == 0

    @pytest.mark.asyncio
    async def test_workspace_isolation(self, mapper, event_bus):
        """Same platform user in different workspaces creates different internal users."""
        user_ws1 = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="12345",
            workspace_id="ws_1",
            event_bus=event_bus,
            display_name="Ivan",
        )
        user_ws2 = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="12345",
            workspace_id="ws_2",
            event_bus=event_bus,
            display_name="Ivan",
        )
        assert user_ws1.id != user_ws2.id

    @pytest.mark.asyncio
    async def test_display_name_propagated(self, mapper, event_bus):
        """display_name should be set on the created user."""
        user = await mapper.map_platform_user(
            channel="discord",
            channel_user_id="777",
            workspace_id="ws_1",
            event_bus=event_bus,
            display_name="\u0414\u043c\u0438\u0442\u0440\u0438\u0439",
        )
        stored = await mapper._user_store.get_user_by_id(user.id)
        assert stored["display_name"] == "\u0414\u043c\u0438\u0442\u0440\u0438\u0439"

    @pytest.mark.asyncio
    async def test_cache_hit_no_db_query(self, mapper, event_bus):
        """Cached user should be returned without DB query."""
        user1 = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="111",
            workspace_id="ws_1",
            event_bus=event_bus,
            display_name="Cached",
        )
        await mapper._engine.dispose()

        user2 = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="111",
            workspace_id="ws_1",
            event_bus=event_bus,
        )
        assert user2.id == user1.id

    @pytest.mark.asyncio
    async def test_cache_expires(self, mapper, event_bus):
        """After TTL expires, cache miss triggers DB lookup."""
        await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="222",
            workspace_id="ws_1",
            event_bus=event_bus,
            display_name="Expire",
        )
        key = ("telegram", "222", "ws_1")
        ts, user = mapper._cache[key]
        mapper._cache[key] = (ts - _CACHE_TTL_SECONDS - 1, user)

        user2 = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="222",
            workspace_id="ws_1",
            event_bus=event_bus,
        )
        assert user2 is not None
        assert len(event_bus.emitted) == 1

    @pytest.mark.asyncio
    async def test_no_event_bus_still_works(self, mapper):
        """map_platform_user works without event_bus (event_bus=None)."""
        user = await mapper.map_platform_user(
            channel="telegram",
            channel_user_id="333",
            workspace_id="ws_1",
            display_name="NoBus",
        )
        assert user is not None
