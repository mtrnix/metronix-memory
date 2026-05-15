"""ChatPersistence — async DAO over chat_threads + chat_messages (MTRNIX-353, T3).

All methods use parameterised SQLAlchemy text() queries — no ORM, no raw string
concatenation. Engine is injected at construction: no global state.

Workspace isolation guarantee: every query that accepts a workspace_id filters by
it so a caller cannot read or write across workspace boundaries (except the
cross-workspace user-cascade delete, which is intentional for ASOC user deletion).
"""

from __future__ import annotations

import json
from datetime import datetime  # noqa: TC003 — used in method signatures (runtime)
from typing import Any
from uuid import UUID  # noqa: TC003 — used in method signatures (runtime)

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine  # noqa: TC002 — constructor parameter type

from metatron.chat.models import ChatMessage, ChatMessageRole, ChatThread  # noqa: TC001 — runtime
from metatron.core.exceptions import ChatThreadNotFoundError

logger = structlog.get_logger(__name__)


def _row_to_thread(row: Any) -> ChatThread:  # noqa: ANN401
    m = row._mapping
    return ChatThread(
        thread_id=UUID(str(m["thread_id"])),
        workspace_id=str(m["workspace_id"]),
        user_id=str(m["user_id"]),
        created_at=m["created_at"],
        last_message_at=m.get("last_message_at"),
    )


def _row_to_message(row: Any) -> ChatMessage:  # noqa: ANN401
    m = row._mapping
    raw_citations = m.get("citations_json")
    raw_tool_calls = m.get("tool_calls_json")

    # PG JSON columns may return dicts/lists or raw strings depending on driver.
    def _parse_json_col(val: Any) -> list[dict[str, Any]] | None:  # noqa: ANN401
        if val is None:
            return None
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            parsed: list[dict[str, Any]] = json.loads(val)
            return parsed
        return list(val)

    return ChatMessage(
        id=UUID(str(m["id"])),
        thread_id=UUID(str(m["thread_id"])),
        role=ChatMessageRole(str(m["role"])),
        content=str(m["content"]),
        citations_json=_parse_json_col(raw_citations),
        tool_calls_json=_parse_json_col(raw_tool_calls),
        created_at=m["created_at"],
    )


class ChatPersistence:
    """Async DAO for persistent chat history.

    Parameters
    ----------
    engine:
        An already-configured :class:`~sqlalchemy.ext.asyncio.AsyncEngine`.
        This class does not create or close the engine — that is the caller's
        responsibility.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    async def get_or_create_thread(self, workspace_id: str, user_id: str) -> ChatThread:
        """Return existing thread or create a new one (upsert, idempotent).

        The ON CONFLICT DO UPDATE no-op forces RETURNING to fire on conflict
        so we always get the row back in a single round-trip.
        """
        sql = text("""
            INSERT INTO chat_threads (workspace_id, user_id)
            VALUES (:w, :u)
            ON CONFLICT (workspace_id, user_id)
            DO UPDATE SET workspace_id = EXCLUDED.workspace_id
            RETURNING *
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"w": workspace_id, "u": user_id})
            row = result.first()
        assert row is not None, "RETURNING must yield a row"
        return _row_to_thread(row)

    async def get_thread(self, workspace_id: str, thread_id: UUID) -> ChatThread | None:
        """Fetch thread by id, scoped to workspace. Returns None on miss or cross-workspace."""
        sql = text("""
            SELECT * FROM chat_threads
            WHERE thread_id = :tid AND workspace_id = :w
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"tid": str(thread_id), "w": workspace_id})
            row = result.first()
        if row is None:
            return None
        return _row_to_thread(row)

    async def list_threads(self, workspace_id: str, user_id: str) -> list[ChatThread]:
        """List threads for a (workspace, user) pair, newest first."""
        sql = text("""
            SELECT * FROM chat_threads
            WHERE workspace_id = :w AND user_id = :u
            ORDER BY created_at DESC
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"w": workspace_id, "u": user_id})
            rows = result.fetchall()
        return [_row_to_thread(r) for r in rows]

    async def delete_thread(self, workspace_id: str, thread_id: UUID) -> bool:
        """Delete thread (and cascade-delete messages). Returns True if a row was deleted."""
        sql = text("""
            DELETE FROM chat_threads
            WHERE thread_id = :tid AND workspace_id = :w
            RETURNING thread_id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"tid": str(thread_id), "w": workspace_id})
            row = result.first()
        return row is not None

    async def delete_threads_for_user(self, user_id: str) -> int:
        """Delete ALL threads for a user across ALL workspaces (ASOC user-cascade).

        Cross-workspace by design — called only from the admin cascade endpoint.
        Returns the number of threads deleted.
        """
        sql = text("""
            DELETE FROM chat_threads
            WHERE user_id = :u
            RETURNING thread_id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"u": user_id})
            rows = result.fetchall()
        return len(rows)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def append_message(
        self,
        workspace_id: str,
        thread_id: UUID,
        role: ChatMessageRole,
        content: str,
        citations_json: list[dict[str, Any]] | None = None,
        tool_calls_json: list[dict[str, Any]] | None = None,
    ) -> ChatMessage:
        """Append a message to a thread.

        Raises :class:`~metatron.core.exceptions.ChatThreadNotFoundError`
        if the thread does not exist in this workspace.

        The operation runs in a single transaction:
        1. Verify thread ownership (workspace_id check).
        2. Insert the message row.
        3. Update ``last_message_at`` on the parent thread.
        """
        tid_str = str(thread_id)
        check_sql = text("""
            SELECT 1 FROM chat_threads
            WHERE thread_id = :tid AND workspace_id = :w
        """)
        insert_sql = text("""
            INSERT INTO chat_messages
                (thread_id, role, content, citations_json, tool_calls_json)
            VALUES (:tid, :role, :content, :citations, :tool_calls)
            RETURNING *
        """)
        touch_sql = text("""
            UPDATE chat_threads
            SET last_message_at = NOW()
            WHERE thread_id = :tid
        """)
        async with self._engine.begin() as conn:
            check = await conn.execute(check_sql, {"tid": tid_str, "w": workspace_id})
            if check.first() is None:
                raise ChatThreadNotFoundError(
                    f"Thread {thread_id} not found in workspace {workspace_id}"
                )
            insert_result = await conn.execute(
                insert_sql,
                {
                    "tid": tid_str,
                    "role": str(role),
                    "content": content,
                    "citations": (
                        json.dumps(citations_json) if citations_json is not None else None
                    ),
                    "tool_calls": (
                        json.dumps(tool_calls_json) if tool_calls_json is not None else None
                    ),
                },
            )
            msg_row = insert_result.first()
            assert msg_row is not None
            await conn.execute(touch_sql, {"tid": tid_str})

        return _row_to_message(msg_row)

    async def list_messages(
        self,
        workspace_id: str,
        thread_id: UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ChatMessage]:
        """List messages for a thread (oldest first), workspace-scoped.

        Cross-workspace reads return an empty list (thread JOIN enforces ownership).
        """
        tid_str = str(thread_id)
        if limit is not None:
            sql = text("""
                SELECT m.*
                FROM chat_messages m
                JOIN chat_threads t USING (thread_id)
                WHERE t.thread_id = :tid AND t.workspace_id = :w
                ORDER BY m.created_at ASC
                LIMIT :lim OFFSET :off
            """)
            params: dict[str, Any] = {
                "tid": tid_str,
                "w": workspace_id,
                "lim": limit,
                "off": offset,
            }
        else:
            sql = text("""
                SELECT m.*
                FROM chat_messages m
                JOIN chat_threads t USING (thread_id)
                WHERE t.thread_id = :tid AND t.workspace_id = :w
                ORDER BY m.created_at ASC
                OFFSET :off
            """)
            params = {"tid": tid_str, "w": workspace_id, "off": offset}

        async with self._engine.begin() as conn:
            result = await conn.execute(sql, params)
            rows = result.fetchall()
        return [_row_to_message(r) for r in rows]

    # ------------------------------------------------------------------
    # Cleanup (cron)
    # ------------------------------------------------------------------

    async def delete_messages_older_than(self, cutoff: datetime) -> int:
        """Delete all messages older than ``cutoff`` (global, no workspace scope — cron only).

        Returns the count of deleted rows.
        """
        sql = text("""
            DELETE FROM chat_messages
            WHERE created_at < :cutoff
            RETURNING id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"cutoff": cutoff})
            rows = result.fetchall()
        return len(rows)

    async def delete_threads_for_workspace(self, workspace_id: str) -> int:
        """Delete all chat threads (and via FK CASCADE, all messages) for a workspace.

        Used by WorkspaceManager.delete() for cascade teardown.  Cross-user by
        design — deletes threads for every user of this workspace.

        Returns the number of threads deleted.
        """
        sql = text("""
            DELETE FROM chat_threads
            WHERE workspace_id = :workspace_id
            RETURNING thread_id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"workspace_id": workspace_id})
            rows = result.fetchall()
        deleted = len(rows)
        logger.info(
            "chat.threads.deleted_for_workspace",
            workspace_id=workspace_id,
            count=deleted,
        )
        return deleted

    async def delete_orphan_threads(self, cutoff: datetime) -> int:
        """Delete threads that have no messages and are older than ``cutoff``.

        A thread becomes an orphan after ``delete_messages_older_than`` removes
        all its messages. The sub-query uses a LEFT JOIN so threads with zero
        messages match; ``last_message_at`` fallback to ``created_at`` covers
        threads that were never written to.

        Returns the count of deleted threads.
        """
        sql = text("""
            DELETE FROM chat_threads
            WHERE thread_id IN (
                SELECT t.thread_id
                FROM chat_threads t
                LEFT JOIN chat_messages m USING (thread_id)
                WHERE m.thread_id IS NULL
                  AND (
                        t.last_message_at < :cutoff
                        OR (t.last_message_at IS NULL AND t.created_at < :cutoff)
                      )
            )
            RETURNING thread_id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"cutoff": cutoff})
            rows = result.fetchall()
        return len(rows)
