"""Tests for MemoryPostgresStore.count_records() and .update() (MTRNIX-310)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.mcp.tools.memory_update import metatron_memory_update
from metatron.storage.memory_postgres import MemoryPostgresStore

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_memory_postgres.py)
# ---------------------------------------------------------------------------

_RECORD_ROW = {
    "id": "mem001",
    "workspace_id": "ws1",
    "agent_id": "agent1",
    "scope": "per_agent",
    "source_type": "conversation",
    "content": "user prefers dark mode",
    "tags": ["preference"],
    "importance_score": 0.8,
    "ttl_expires_at": None,
    "content_hash": "abc123",
    "session_id": None,
    "metadata": {},
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
}


def _make_store() -> tuple[MemoryPostgresStore, MagicMock]:
    engine = MagicMock()
    store = MemoryPostgresStore(engine)
    return store, engine


def _mock_row(row_data: dict) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: row_data[k]
    mapping.get = lambda k, default=None: row_data.get(k, default)
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


# ===========================================================================
# count_records
# ===========================================================================


class TestCountRecords:
    async def test_count_returns_scalar(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 42
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        count = await store.count_records("ws1")

        assert count == 42
        sql_text = str(conn.execute.call_args.args[0])
        assert "count(*)" in sql_text
        params = conn.execute.call_args.args[1]
        assert params["workspace_id"] == "ws1"

    async def test_count_with_scope_filter(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 5
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        count = await store.count_records(
            "ws1", agent_id="agent1", scope=MemoryScope.PER_AGENT
        )

        assert count == 5
        sql_text = str(conn.execute.call_args.args[0])
        assert "agent_id" in sql_text
        assert "scope" in sql_text
        params = conn.execute.call_args.args[1]
        assert params["agent_id"] == "agent1"
        assert params["scope"] == "per_agent"


# ===========================================================================
# update
# ===========================================================================


class TestUpdate:
    async def test_update_content(self) -> None:
        store, engine = _make_store()

        # We need two engine.begin() calls: first for get(), second for update(),
        # third for the re-fetch get().
        call_count = 0

        def _begin():
            nonlocal call_count
            call_count += 1
            conn = AsyncMock()
            result = MagicMock()

            if call_count in (1, 3):
                # get() calls — return existing record
                row_data = dict(_RECORD_ROW)
                if call_count == 3:
                    # After update, content and hash should be new
                    row_data["content"] = "new content"
                    row_data["content_hash"] = hashlib.sha256(
                        b"new content"
                    ).hexdigest()
                row = _mock_row(row_data)
                result.first.return_value = row
            else:
                # update() call
                result.rowcount = 1

            conn.execute.return_value = result
            return _FakeCtx(conn)

        engine.begin.side_effect = _begin

        updated = await store.update("ws1", "mem001", content="new content")

        assert updated is not None
        assert updated.content == "new content"
        assert updated.content_hash == hashlib.sha256(b"new content").hexdigest()

    async def test_update_not_found(self) -> None:
        store, engine = _make_store()
        conn = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        conn.execute.return_value = result
        engine.begin.return_value = _FakeCtx(conn)

        updated = await store.update("ws1", "nonexistent", content="new")

        assert updated is None


# ===========================================================================
# MCP tool: metatron_memory_update
# ===========================================================================

def _make_memory_record(**overrides: Any) -> MemoryRecord:
    defaults = {
        "id": "mem001",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "source_type": "conversation",
        "content": "user prefers dark mode",
        "tags": ["preference"],
        "importance_score": 0.8,
        "content_hash": "abc123",
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


class TestMemoryUpdateTool:
    @patch("metatron.mcp.tools.memory_update.upsert_memory_node")
    @patch("metatron.mcp.tools.memory_update._memory_deps")
    async def test_update_content(
        self, mock_deps: MagicMock, mock_upsert_node: MagicMock
    ) -> None:
        updated_record = _make_memory_record(
            content="new content",
            content_hash=hashlib.sha256(b"new content").hexdigest(),
        )
        service = AsyncMock()
        service.pg_store.update = AsyncMock(return_value=updated_record)
        service.qdrant_store.upsert = AsyncMock()
        service.qdrant_store.update_payload = AsyncMock()
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)
        mock_upsert_node.return_value = None

        result = await metatron_memory_update(
            record_id="mem001",
            workspace_id="ws1",
            content="new content",
        )

        assert "error" not in result
        assert result["id"] == "mem001"
        assert result["updated_fields"] == ["content"]
        service.qdrant_store.upsert.assert_awaited_once_with(updated_record)
        service.qdrant_store.update_payload.assert_not_awaited()

    @patch("metatron.mcp.tools.memory_update.upsert_memory_node")
    @patch("metatron.mcp.tools.memory_update._memory_deps")
    async def test_update_tags_only_no_reembed(
        self, mock_deps: MagicMock, mock_upsert_node: MagicMock
    ) -> None:
        updated_record = _make_memory_record(tags=["new-tag"])
        service = AsyncMock()
        service.pg_store.update = AsyncMock(return_value=updated_record)
        service.qdrant_store.upsert = AsyncMock()
        service.qdrant_store.update_payload = AsyncMock()
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)
        mock_upsert_node.return_value = None

        result = await metatron_memory_update(
            record_id="mem001",
            workspace_id="ws1",
            tags=["new-tag"],
        )

        assert "error" not in result
        assert result["updated_fields"] == ["tags"]
        service.qdrant_store.update_payload.assert_awaited_once_with(
            "mem001", {"tags": ["new-tag"]}
        )
        service.qdrant_store.upsert.assert_not_awaited()

    @patch("metatron.mcp.tools.memory_update._memory_deps")
    async def test_not_found(self, mock_deps: MagicMock) -> None:
        service = AsyncMock()
        service.pg_store.update = AsyncMock(return_value=None)
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_update(
            record_id="nonexistent",
            workspace_id="ws1",
            content="new",
        )

        assert "error" in result
        assert "not found" in result["error"]["message"].lower()

    async def test_no_fields_returns_error(self) -> None:
        result = await metatron_memory_update(record_id="mem001")

        assert "error" in result
        assert "at least one" in result["error"]["message"].lower()
