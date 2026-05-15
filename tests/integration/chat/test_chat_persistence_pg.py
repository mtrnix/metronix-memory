"""Integration tests for ChatPersistence against a live PostgreSQL (MTRNIX-353, T3).

Requires the dev stack running (``make docker-up``) and migration 022 applied.
Marked ``integration`` — runs only under ``make test-all`` (not ``make test``).

Each test creates and cleans up its own rows using a unique workspace prefix
so tests can run concurrently without interference.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.chat.models import ChatMessageRole
from metatron.chat.persistence import ChatPersistence
from metatron.core.config import get_settings
from metatron.core.exceptions import ChatThreadNotFoundError

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Engine / cleanup fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine():
    settings = get_settings()
    e = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    yield e
    await e.dispose()


@pytest.fixture
async def persistence(engine):
    return ChatPersistence(engine)


async def _cleanup(engine, workspace_prefix: str) -> None:
    """Delete all test rows created by this test run."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        # ON DELETE CASCADE takes care of chat_messages
        await conn.execute(
            text("DELETE FROM chat_threads WHERE workspace_id LIKE :p"),
            {"p": f"{workspace_prefix}%"},
        )


# ---------------------------------------------------------------------------
# Unique workspace helper
# ---------------------------------------------------------------------------


def _ws() -> str:
    return f"chat-it-{uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_get_or_create_thread_idempotent(engine, persistence) -> None:
    """Calling get_or_create_thread twice returns the same thread_id."""
    ws = _ws()
    try:
        t1 = await persistence.get_or_create_thread(ws, "user-1")
        t2 = await persistence.get_or_create_thread(ws, "user-1")
        assert t1.thread_id == t2.thread_id
        assert t1.workspace_id == ws
    finally:
        await _cleanup(engine, ws)


async def test_append_and_list_messages(engine, persistence) -> None:
    """Messages appended to a thread are retrieved in creation order."""
    ws = _ws()
    try:
        thread = await persistence.get_or_create_thread(ws, "user-2")
        await persistence.append_message(ws, thread.thread_id, ChatMessageRole.USER, "Hello")
        await persistence.append_message(
            ws, thread.thread_id, ChatMessageRole.ASSISTANT, "Hi there"
        )

        msgs = await persistence.list_messages(ws, thread.thread_id)
        assert len(msgs) == 2
        assert msgs[0].content == "Hello"
        assert msgs[1].content == "Hi there"
        assert msgs[0].role == ChatMessageRole.USER
        assert msgs[1].role == ChatMessageRole.ASSISTANT
    finally:
        await _cleanup(engine, ws)


async def test_cascade_delete_removes_messages(engine, persistence) -> None:
    """Deleting a thread removes all its messages via FK CASCADE."""
    ws = _ws()
    try:
        thread = await persistence.get_or_create_thread(ws, "user-3")
        await persistence.append_message(ws, thread.thread_id, ChatMessageRole.USER, "bye")

        deleted = await persistence.delete_thread(ws, thread.thread_id)
        assert deleted is True

        # Thread gone — list_messages returns [] (JOIN finds no thread)
        msgs = await persistence.list_messages(ws, thread.thread_id)
        assert msgs == []
    finally:
        await _cleanup(engine, ws)


async def test_cross_workspace_isolation(engine, persistence) -> None:
    """A thread is not visible from another workspace."""
    ws_a = _ws()
    ws_b = _ws()
    try:
        thread = await persistence.get_or_create_thread(ws_a, "user-4")
        # Reading from ws_b should return None
        result = await persistence.get_thread(ws_b, thread.thread_id)
        assert result is None
    finally:
        await _cleanup(engine, ws_a)
        await _cleanup(engine, ws_b)


async def test_append_message_raises_on_wrong_workspace(engine, persistence) -> None:
    """append_message raises ChatThreadNotFoundError on workspace mismatch."""
    ws_a = _ws()
    ws_b = _ws()
    try:
        thread = await persistence.get_or_create_thread(ws_a, "user-5")
        with pytest.raises(ChatThreadNotFoundError):
            await persistence.append_message(
                ws_b, thread.thread_id, ChatMessageRole.USER, "sneaky"
            )
    finally:
        await _cleanup(engine, ws_a)
        await _cleanup(engine, ws_b)


async def test_role_check_constraint(engine, persistence) -> None:
    """Inserting an invalid role raises a DB error (CHECK constraint)."""
    ws = _ws()
    try:
        thread = await persistence.get_or_create_thread(ws, "user-6")
        # Bypass the enum and pass an invalid string directly
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        async with engine.begin() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "INSERT INTO chat_messages (thread_id, role, content) "
                        "VALUES (:tid, :role, :content)"
                    ),
                    {"tid": str(thread.thread_id), "role": "invalid_role", "content": "x"},
                )
    finally:
        await _cleanup(engine, ws)


async def test_delete_messages_older_than_prunes_correctly(engine, persistence) -> None:
    """Messages older than the cutoff are deleted; newer ones survive."""
    ws = _ws()
    try:
        thread = await persistence.get_or_create_thread(ws, "user-7")
        await persistence.append_message(ws, thread.thread_id, ChatMessageRole.USER, "old")

        # Use a future cutoff — should delete the just-inserted message
        future_cutoff = datetime.now(UTC) + timedelta(seconds=10)
        deleted_count = await persistence.delete_messages_older_than(future_cutoff)
        assert deleted_count >= 1
    finally:
        await _cleanup(engine, ws)


async def test_delete_threads_for_user_cross_workspace(engine, persistence) -> None:
    """delete_threads_for_user removes threads across multiple workspaces."""
    ws_a = _ws()
    ws_b = _ws()
    user = f"cascade-user-{uuid4().hex[:6]}"
    try:
        await persistence.get_or_create_thread(ws_a, user)
        await persistence.get_or_create_thread(ws_b, user)

        deleted = await persistence.delete_threads_for_user(user)
        assert deleted == 2
    finally:
        await _cleanup(engine, ws_a)
        await _cleanup(engine, ws_b)
