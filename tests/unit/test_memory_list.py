"""Tests for MCP memory_list tool (MTRNIX-310)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from metatron.core.models import MemoryRecord, MemoryScope


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


def _mock_service(
    records: list[MemoryRecord] | None = None,
    total: int = 0,
) -> AsyncMock:
    service = AsyncMock()
    service.pg_store = AsyncMock()
    service.pg_store.list_records = AsyncMock(return_value=records or [])
    service.pg_store.count_records = AsyncMock(return_value=total)
    return service


class TestMemoryList:
    async def test_happy_path(self) -> None:
        record = _make_record(id="rec-42", content="important fact")
        service = _mock_service(records=[record], total=42)

        with patch(
            "metatron.mcp.tools.memory_list._memory_deps.build_memory_service_for_workspace",
            new=AsyncMock(return_value=service),
        ):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(agent_id="agent-a")

        assert "error" not in out
        assert out["count"] == 1
        assert out["total"] == 42
        assert out["records"][0]["id"] == "rec-42"
        service.pg_store.list_records.assert_awaited_once()
        service.pg_store.count_records.assert_awaited_once()

    async def test_empty_results(self) -> None:
        service = _mock_service(records=[], total=0)

        with patch(
            "metatron.mcp.tools.memory_list._memory_deps.build_memory_service_for_workspace",
            new=AsyncMock(return_value=service),
        ):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(agent_id="agent-a")

        assert "error" not in out
        assert out["count"] == 0
        assert out["total"] == 0
        assert out["records"] == []

    async def test_missing_agent_id_returns_error(self) -> None:
        from metatron.mcp.tools.memory_list import metatron_memory_list

        out = await metatron_memory_list(agent_id="")

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"

    async def test_tags_post_filter(self) -> None:
        rec_match = _make_record(id="rec-match", tags=["important", "todo"])
        rec_skip = _make_record(id="rec-skip", tags=["other"])
        service = _mock_service(records=[rec_match, rec_skip], total=2)

        with patch(
            "metatron.mcp.tools.memory_list._memory_deps.build_memory_service_for_workspace",
            new=AsyncMock(return_value=service),
        ):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(
                agent_id="agent-a",
                tags=["important"],
            )

        assert "error" not in out
        assert out["count"] == 1
        assert out["records"][0]["id"] == "rec-match"
        # total reflects DB count (before tag filter)
        assert out["total"] == 2
