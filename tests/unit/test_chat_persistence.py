"""Unit tests for ChatPersistence DAO (MTRNIX-353, T3).

Uses mock engine — no live DB required. Asserts SQL text and parameters.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from metatron.chat.models import ChatMessageRole, ChatThread
from metatron.chat.persistence import ChatPersistence
from metatron.core.exceptions import ChatThreadNotFoundError

_WS = "ws-asoc-1"
_USER = "user-42"
_THREAD_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_MSG_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Mock helpers — mirrors test_memory_postgres.py style
# ---------------------------------------------------------------------------


def _make_row(data: dict[str, Any]) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: data[k]
    mapping.get = lambda k, default=None: data.get(k, default)
    row = MagicMock()
    row._mapping = mapping
    return row


class _FakeCtx:
    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        pass


def _make_store_and_conn(row_data: dict | None = None, rowcount: int = 1):
    engine = MagicMock()
    conn = AsyncMock()
    result = MagicMock()
    result.rowcount = rowcount
    if row_data is not None:
        row = _make_row(row_data)
        result.first.return_value = row
        result.fetchall.return_value = [row]
    else:
        result.first.return_value = None
        result.fetchall.return_value = []
    conn.execute.return_value = result
    engine.begin.return_value = _FakeCtx(conn)
    store = ChatPersistence(engine)
    return store, conn


# ---------------------------------------------------------------------------
# Row fixtures
# ---------------------------------------------------------------------------

_THREAD_ROW: dict[str, Any] = {
    "thread_id": str(_THREAD_ID),
    "workspace_id": _WS,
    "user_id": _USER,
    "created_at": _NOW,
    "last_message_at": None,
}

_MSG_ROW: dict[str, Any] = {
    "id": str(_MSG_ID),
    "thread_id": str(_THREAD_ID),
    "role": "user",
    "content": "Hello ASOC",
    "citations_json": None,
    "tool_calls_json": None,
    "created_at": _NOW,
}


# ===========================================================================
# get_or_create_thread
# ===========================================================================


class TestGetOrCreateThread:
    async def test_happy_path_returns_thread(self) -> None:
        store, conn = _make_store_and_conn(_THREAD_ROW)

        thread = await store.get_or_create_thread(_WS, _USER)

        assert thread.thread_id == _THREAD_ID
        assert thread.workspace_id == _WS
        assert thread.user_id == _USER
        assert thread.last_message_at is None

    async def test_executes_upsert_sql(self) -> None:
        store, conn = _make_store_and_conn(_THREAD_ROW)

        await store.get_or_create_thread(_WS, _USER)

        call_args = conn.execute.call_args.args
        sql_str = str(call_args[0]).lower()
        assert "insert into chat_threads" in sql_str
        assert "on conflict" in sql_str
        params = call_args[1]
        assert params["w"] == _WS
        assert params["u"] == _USER

    async def test_idempotent_on_conflict(self) -> None:
        """Calling twice should produce the same thread (ON CONFLICT DO UPDATE)."""
        store, conn = _make_store_and_conn(_THREAD_ROW)

        t1 = await store.get_or_create_thread(_WS, _USER)
        t2 = await store.get_or_create_thread(_WS, _USER)

        assert t1.thread_id == t2.thread_id


# ===========================================================================
# get_thread
# ===========================================================================


class TestGetThread:
    async def test_returns_thread_when_found(self) -> None:
        store, _ = _make_store_and_conn(_THREAD_ROW)

        thread = await store.get_thread(_WS, _THREAD_ID)

        assert thread is not None
        assert thread.thread_id == _THREAD_ID
        assert thread.workspace_id == _WS

    async def test_returns_none_when_not_found(self) -> None:
        store, _ = _make_store_and_conn(None)

        thread = await store.get_thread(_WS, _THREAD_ID)

        assert thread is None

    async def test_cross_workspace_returns_none(self) -> None:
        """DB query filters by workspace_id — cross-workspace returns no row."""
        store, conn = _make_store_and_conn(None)

        thread = await store.get_thread("other-workspace", _THREAD_ID)

        assert thread is None
        # Verify workspace_id is in the params
        params = conn.execute.call_args.args[1]
        assert params["w"] == "other-workspace"


# ===========================================================================
# list_threads
# ===========================================================================


class TestListThreads:
    async def test_returns_list_of_threads(self) -> None:
        store, _ = _make_store_and_conn(_THREAD_ROW)

        threads = await store.list_threads(_WS, _USER)

        assert len(threads) == 1
        assert isinstance(threads[0], ChatThread)

    async def test_empty_when_no_threads(self) -> None:
        store, _ = _make_store_and_conn(None)

        threads = await store.list_threads(_WS, _USER)

        assert threads == []


# ===========================================================================
# append_message
# ===========================================================================


class TestAppendMessage:
    def _make_store_for_append(self, thread_exists: bool = True):
        """Set up engine with sequential execute() calls.

        T4 rewrite uses single-statement INSERT ... SELECT ... WHERE EXISTS
        followed by an UPDATE — so only 2 execute() calls per append_message,
        not 3. When the thread does not exist, INSERT returns no row and the
        UPDATE is skipped.
        """
        engine = MagicMock()
        conn = AsyncMock()

        # First call: INSERT ... SELECT ... WHERE EXISTS RETURNING *
        insert_result = MagicMock()
        if thread_exists:
            msg_row = _make_row(_MSG_ROW)
            insert_result.first.return_value = msg_row
        else:
            insert_result.first.return_value = None

        # Second call (only if thread exists): UPDATE chat_threads SET last_message_at
        update_result = MagicMock()

        if thread_exists:
            conn.execute.side_effect = [insert_result, update_result]
        else:
            conn.execute.side_effect = [insert_result]
        engine.begin.return_value = _FakeCtx(conn)
        return ChatPersistence(engine), conn

    async def test_happy_path_returns_message(self) -> None:
        store, _ = self._make_store_for_append(thread_exists=True)

        msg = await store.append_message(_WS, _THREAD_ID, ChatMessageRole.USER, "Hello")

        # The mock RETURNING row has content "Hello ASOC" (from _MSG_ROW fixture)
        assert msg.id == _MSG_ID
        assert msg.role == ChatMessageRole.USER
        assert msg.content == _MSG_ROW["content"]

    async def test_raises_when_thread_not_found(self) -> None:
        store, _ = self._make_store_for_append(thread_exists=False)

        with pytest.raises(ChatThreadNotFoundError):
            await store.append_message(_WS, _THREAD_ID, ChatMessageRole.USER, "Hello")

    async def test_cross_workspace_raises(self) -> None:
        """Wrong workspace → thread check returns None → raises."""
        store, _ = self._make_store_for_append(thread_exists=False)

        with pytest.raises(ChatThreadNotFoundError):
            await store.append_message("wrong-ws", _THREAD_ID, ChatMessageRole.USER, "Hi")

    async def test_passes_citations_json(self) -> None:
        store, conn = self._make_store_for_append(thread_exists=True)
        cit = [{"source": "doc-1", "text": "excerpt"}]

        await store.append_message(
            _WS, _THREAD_ID, ChatMessageRole.ASSISTANT, "Answer", citations_json=cit
        )

        # First execute call is the INSERT (T4 atomic rewrite); params should
        # have serialised citations.
        insert_call_args = conn.execute.call_args_list[0].args
        params = insert_call_args[1]
        assert params["citations"] == json.dumps(cit)

    async def test_none_citations_passed_as_none(self) -> None:
        store, conn = self._make_store_for_append(thread_exists=True)

        await store.append_message(_WS, _THREAD_ID, ChatMessageRole.USER, "Hi")

        insert_call_args = conn.execute.call_args_list[0].args
        params = insert_call_args[1]
        assert params["citations"] is None


# ===========================================================================
# list_messages
# ===========================================================================


class TestListMessages:
    async def test_returns_messages(self) -> None:
        store, _ = _make_store_and_conn(_MSG_ROW)

        msgs = await store.list_messages(_WS, _THREAD_ID)

        assert len(msgs) == 1
        assert msgs[0].content == "Hello ASOC"

    async def test_with_limit_includes_limit_in_sql(self) -> None:
        store, conn = _make_store_and_conn(_MSG_ROW)

        await store.list_messages(_WS, _THREAD_ID, limit=10, offset=5)

        params = conn.execute.call_args.args[1]
        assert params["lim"] == 10
        assert params["off"] == 5

    async def test_without_limit_clamps_to_hard_cap(self) -> None:
        """T4 enforces a hard cap (1000) on list_messages; lim is always set."""
        store, conn = _make_store_and_conn(_MSG_ROW)

        await store.list_messages(_WS, _THREAD_ID)

        params = conn.execute.call_args.args[1]
        assert params["lim"] == 1000  # _LIST_MESSAGES_HARD_CAP
        assert params["off"] == 0

    async def test_citations_json_parsed(self) -> None:
        cit = [{"source": "doc-1"}]
        row_with_citations = dict(_MSG_ROW, citations_json=json.dumps(cit))
        store, _ = _make_store_and_conn(row_with_citations)

        msgs = await store.list_messages(_WS, _THREAD_ID)

        assert msgs[0].citations_json == cit


# ===========================================================================
# delete_thread
# ===========================================================================


class TestDeleteThread:
    async def test_returns_true_when_deleted(self) -> None:
        store, _ = _make_store_and_conn({"thread_id": str(_THREAD_ID)})

        deleted = await store.delete_thread(_WS, _THREAD_ID)

        assert deleted is True

    async def test_returns_false_when_not_found(self) -> None:
        store, _ = _make_store_and_conn(None)

        deleted = await store.delete_thread(_WS, _THREAD_ID)

        assert deleted is False

    async def test_workspace_scoped(self) -> None:
        store, conn = _make_store_and_conn(None)

        await store.delete_thread("other-ws", _THREAD_ID)

        params = conn.execute.call_args.args[1]
        assert params["w"] == "other-ws"


# ===========================================================================
# delete_threads_for_user
# ===========================================================================


class TestDeleteThreadsForUser:
    async def test_returns_count_of_deleted_threads(self) -> None:
        store, _ = _make_store_and_conn({"thread_id": str(_THREAD_ID)})

        count = await store.delete_threads_for_user(_USER)

        assert count == 1

    async def test_returns_zero_when_no_threads(self) -> None:
        store, _ = _make_store_and_conn(None)

        count = await store.delete_threads_for_user(_USER)

        assert count == 0

    async def test_cross_workspace_by_design(self) -> None:
        """delete_threads_for_user is intentionally cross-workspace."""
        store, conn = _make_store_and_conn(None)

        await store.delete_threads_for_user(_USER)

        params = conn.execute.call_args.args[1]
        assert params["u"] == _USER
        # No workspace_id in params — intentional
        assert "w" not in params


# ===========================================================================
# delete_messages_older_than
# ===========================================================================


class TestDeleteMessagesOlderThan:
    async def test_returns_count(self) -> None:
        store, _ = _make_store_and_conn({"id": str(_MSG_ID)})

        count = await store.delete_messages_older_than(_NOW)

        assert count == 1

    async def test_passes_cutoff_param(self) -> None:
        store, conn = _make_store_and_conn(None)

        await store.delete_messages_older_than(_NOW)

        params = conn.execute.call_args.args[1]
        assert params["cutoff"] == _NOW


# ===========================================================================
# delete_orphan_threads
# ===========================================================================


class TestDeleteOrphanThreads:
    async def test_returns_count(self) -> None:
        store, _ = _make_store_and_conn({"thread_id": str(_THREAD_ID)})

        count = await store.delete_orphan_threads(_NOW)

        assert count == 1

    async def test_passes_cutoff_param(self) -> None:
        store, conn = _make_store_and_conn(None)

        await store.delete_orphan_threads(_NOW)

        params = conn.execute.call_args.args[1]
        assert params["cutoff"] == _NOW
