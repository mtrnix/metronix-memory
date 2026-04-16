"""Tests for MCP memory tools (MTRNIX-303).

Covers ``metatron_memory_search``, ``metatron_memory_store``,
``metatron_memory_delete`` — all tools mock the MemoryService layer, so no
live Postgres/Qdrant/Redis connection is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from metatron.core.models import MemoryRecord, MemoryScope, MemorySearchResult

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
    """Patch the MemoryService factory. Tool modules access it via
    ``_memory_deps.build_memory_service_for_workspace`` so a single patch on
    the underlying module attribute covers all three tool entry points.
    """
    return patch(
        "metatron.mcp.tools._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(return_value=service_mock),
    )


# ---------------------------------------------------------------------------
# metatron_memory_search
# ---------------------------------------------------------------------------


class TestMemorySearch:
    async def test_memory_search_happy_path(self) -> None:
        record = _make_record(id="rec-42", content="finding")
        result = MemorySearchResult(
            record=record,
            score=0.9,
            dense_score=0.7,
            sparse_score=0.1,
            graph_score=0.3,
            rank=1,
        )
        service = AsyncMock()
        service.search = AsyncMock(return_value=[result])

        with _patch_service(service):
            from metatron.mcp.tools.memory_search import metatron_memory_search

            out = await metatron_memory_search(
                query="what did we learn",
                agent_id="agent-a",
                workspace_id="default",
            )

        assert "error" not in out
        assert out["count"] == 1
        assert out["results"][0]["record"]["id"] == "rec-42"
        assert out["results"][0]["score"] == 0.9
        assert out["results"][0]["dense_score"] == 0.7
        assert out["results"][0]["session_boost"] == 0.1
        service.search.assert_awaited_once()

    async def test_memory_search_missing_query(self) -> None:
        from metatron.mcp.tools.memory_search import metatron_memory_search

        out = await metatron_memory_search(query="", agent_id="agent-a")
        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"

    async def test_memory_search_service_failure(self) -> None:
        service = AsyncMock()
        service.search = AsyncMock(side_effect=RuntimeError("qdrant down"))

        with _patch_service(service):
            from metatron.mcp.tools.memory_search import metatron_memory_search

            out = await metatron_memory_search(
                query="hello",
                agent_id="agent-a",
            )

        assert "error" in out
        assert out["error"]["code"] in {"INTERNAL_ERROR", "QDRANT_UNAVAILABLE"}


# ---------------------------------------------------------------------------
# metatron_memory_store
# ---------------------------------------------------------------------------


class TestMemoryStore:
    async def test_memory_store_happy_path_per_agent(self) -> None:
        service = AsyncMock()

        async def _save(ws: str, rec: MemoryRecord) -> MemoryRecord:
            # Not deduped — return the same record instance.
            rec.content_hash = "hash-new"
            return rec

        service.save = AsyncMock(side_effect=_save)

        with _patch_service(service):
            from metatron.mcp.tools.memory_store import metatron_memory_store

            out = await metatron_memory_store(
                content="remember this",
                agent_id="agent-a",
                scope="per_agent",
            )

        assert "error" not in out
        assert out["deduped"] is False
        assert out["content_hash"] == "hash-new"
        service.save.assert_awaited_once()

    async def test_memory_store_dedup_detected(self) -> None:
        existing = _make_record(id="existing-id", content_hash="existing-hash")
        service = AsyncMock()
        service.save = AsyncMock(return_value=existing)

        with _patch_service(service):
            from metatron.mcp.tools.memory_store import metatron_memory_store

            out = await metatron_memory_store(
                content="remember this",
                agent_id="agent-a",
            )

        assert "error" not in out
        assert out["deduped"] is True
        assert out["id"] == "existing-id"

    async def test_memory_store_session_requires_session_id(self) -> None:
        from metatron.mcp.tools.memory_store import metatron_memory_store

        out = await metatron_memory_store(
            content="ephemeral",
            agent_id="agent-a",
            scope="session",
        )
        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"
        assert "session_id" in out["error"]["message"]

    async def test_memory_store_session_routes_to_cache(self) -> None:
        record = _make_record(scope=MemoryScope.SESSION, session_id="sess-1")
        service = AsyncMock()
        service.cache_session = AsyncMock(return_value=record)
        service.save = AsyncMock()  # should NOT be called

        with _patch_service(service):
            from metatron.mcp.tools.memory_store import metatron_memory_store

            out = await metatron_memory_store(
                content="ephemeral",
                agent_id="agent-a",
                scope="session",
                session_id="sess-1",
            )

        assert "error" not in out
        service.cache_session.assert_awaited_once()
        service.save.assert_not_called()


# ---------------------------------------------------------------------------
# metatron_memory_delete
# ---------------------------------------------------------------------------


class TestMemoryDelete:
    async def test_memory_delete_found(self) -> None:
        service = AsyncMock()
        service.delete = AsyncMock(return_value=True)

        with _patch_service(service):
            from metatron.mcp.tools.memory_delete import metatron_memory_delete

            out = await metatron_memory_delete(record_id="rec-42")

        assert "error" not in out
        assert out["success"] is True
        assert out["found"] is True
        service.delete.assert_awaited_once_with("default", "rec-42")

    async def test_memory_delete_not_found(self) -> None:
        service = AsyncMock()
        service.delete = AsyncMock(return_value=False)

        with _patch_service(service):
            from metatron.mcp.tools.memory_delete import metatron_memory_delete

            out = await metatron_memory_delete(record_id="nope")

        assert "error" in out
        assert out["error"]["code"] == "DOCUMENT_NOT_FOUND"
