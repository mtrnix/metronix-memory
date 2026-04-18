"""Tests for MCP memory_batch_store tool (MTRNIX-310).

Covers ``metatron_memory_batch_store`` — mocks the MemoryService layer,
so no live Postgres/Qdrant/Redis connection is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from metatron.core.models import MemoryRecord, MemoryScope

if TYPE_CHECKING:
    from contextlib import AbstractContextManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(**overrides: object) -> MemoryRecord:
    base: dict[str, object] = {
        "id": "rec-1",
        "workspace_id": "default",
        "agent_id": "agent-a",
        "scope": MemoryScope.PER_AGENT,
        "source_type": "test",
        "content": "hello world",
        "tags": ["x"],
        "importance_score": 0.5,
        "content_hash": "hash-1",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "session_id": None,
        "metadata": {},
    }
    base.update(overrides)
    return MemoryRecord(**base)  # type: ignore[arg-type]


def _patch_service(service_mock: AsyncMock) -> AbstractContextManager[object]:
    return patch(
        "metatron.mcp.tools._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(return_value=service_mock),
    )


# ---------------------------------------------------------------------------
# metatron_memory_batch_store
# ---------------------------------------------------------------------------


class TestMemoryBatchStore:
    async def test_happy_path_two_records(self) -> None:
        service = AsyncMock()

        async def _save(_ws: str, rec: MemoryRecord) -> MemoryRecord:
            rec.content_hash = f"hash-{rec.content[:4]}"
            return rec

        service.save = AsyncMock(side_effect=_save)

        with _patch_service(service):
            from metatron.mcp.tools.memory_batch_store import (
                metatron_memory_batch_store,
            )

            out = await metatron_memory_batch_store(
                records=[
                    {"content": "first memory", "tags": ["a"]},
                    {"content": "second memory"},
                ],
                agent_id="agent-a",
            )

        assert "error" not in out
        assert out["stored"] == 2
        assert out["deduped"] == 0
        assert len(out["results"]) == 2
        assert out["results"][0]["content_hash"] == "hash-firs"
        assert out["results"][1]["content_hash"] == "hash-seco"
        assert service.save.await_count == 2

    async def test_dedup_detected(self) -> None:
        existing = _make_record(id="existing-id", content_hash="existing-hash")
        service = AsyncMock()
        service.save = AsyncMock(return_value=existing)

        with _patch_service(service):
            from metatron.mcp.tools.memory_batch_store import (
                metatron_memory_batch_store,
            )

            out = await metatron_memory_batch_store(
                records=[{"content": "duplicate content"}],
                agent_id="agent-a",
            )

        assert "error" not in out
        assert out["stored"] == 1
        assert out["deduped"] == 1
        assert out["results"][0]["deduped"] is True
        assert out["results"][0]["id"] == "existing-id"

    async def test_over_limit_returns_error(self) -> None:
        from metatron.mcp.tools.memory_batch_store import (
            metatron_memory_batch_store,
        )

        out = await metatron_memory_batch_store(
            records=[{"content": f"r{i}"} for i in range(101)],
            agent_id="agent-a",
        )
        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"
        assert "101" in out["error"]["message"]

    async def test_empty_records_returns_error(self) -> None:
        from metatron.mcp.tools.memory_batch_store import (
            metatron_memory_batch_store,
        )

        out = await metatron_memory_batch_store(
            records=[],
            agent_id="agent-a",
        )
        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"
        assert "empty" in out["error"]["message"]

    async def test_missing_agent_id_returns_error(self) -> None:
        from metatron.mcp.tools.memory_batch_store import (
            metatron_memory_batch_store,
        )

        out = await metatron_memory_batch_store(
            records=[{"content": "something"}],
            agent_id="",
        )
        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"
        assert "agent_id" in out["error"]["message"]

    async def test_session_scope_calls_cache_session(self) -> None:
        service = AsyncMock()
        stored = MemoryRecord(
            id="id1",
            workspace_id="ws1",
            agent_id="hermes",
            scope=MemoryScope.SESSION,
            source_type="",
            content="session fact",
            content_hash="h1",
            session_id="sess1",
        )
        service.cache_session = AsyncMock(return_value=stored)

        with _patch_service(service):
            from metatron.mcp.tools.memory_batch_store import (
                metatron_memory_batch_store,
            )

            result = await metatron_memory_batch_store(
                records=[{"content": "session fact"}],
                agent_id="hermes",
                workspace_id="ws1",
                scope="session",
                session_id="sess1",
            )

        assert result["stored"] == 1
        service.cache_session.assert_called_once()
        service.save.assert_not_called()
