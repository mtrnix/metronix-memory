"""Unit tests for ``metronix_memory_search`` status filter param (MTRNIX-314)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from metronix.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager


def _make_record(
    record_id: str = "rec-1",
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id="default",
        agent_id="agent-a",
        scope=MemoryScope.PER_AGENT,
        source_type="test",
        content="hello",
        tags=[],
        importance_score=0.5,
        content_hash="h",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        session_id=None,
        metadata={},
        status=status,
    )


def _patch_service(service_mock: AsyncMock) -> AbstractContextManager[object]:
    return patch(
        "metronix.mcp.tools._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(return_value=service_mock),
    )


class TestStatusFilterParam:
    async def test_default_passes_active_only(self) -> None:
        service = AsyncMock()
        service.search = AsyncMock(return_value=[])

        with _patch_service(service):
            from metronix.mcp.tools.memory_search import metronix_memory_search

            out = await metronix_memory_search(
                query="hello", agent_id="agent-a", workspace_id="default"
            )

        assert "error" not in out
        kw = service.search.await_args.kwargs
        assert kw["status_filter"] == [LifecycleStatus.ACTIVE]

    async def test_all_sentinel_passes_none(self) -> None:
        service = AsyncMock()
        service.search = AsyncMock(return_value=[])

        with _patch_service(service):
            from metronix.mcp.tools.memory_search import metronix_memory_search

            out = await metronix_memory_search(
                query="hello",
                agent_id="agent-a",
                workspace_id="default",
                status=["all"],
            )

        assert "error" not in out
        assert service.search.await_args.kwargs["status_filter"] is None

    async def test_include_set_passed_through(self) -> None:
        service = AsyncMock()
        service.search = AsyncMock(return_value=[])

        with _patch_service(service):
            from metronix.mcp.tools.memory_search import metronix_memory_search

            out = await metronix_memory_search(
                query="hello",
                agent_id="agent-a",
                workspace_id="default",
                status=["active", "candidate"],
            )

        assert "error" not in out
        assert service.search.await_args.kwargs["status_filter"] == [
            LifecycleStatus.ACTIVE,
            LifecycleStatus.CANDIDATE,
        ]

    async def test_invalid_status_returns_invalid_params(self) -> None:
        service = AsyncMock()

        with _patch_service(service):
            from metronix.mcp.tools.memory_search import metronix_memory_search

            out = await metronix_memory_search(
                query="hello",
                agent_id="agent-a",
                workspace_id="default",
                status=["bogus"],
            )

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"
        # Service search never called on invalid input.
        service.search.assert_not_called()

    async def test_record_status_populates_dto(self) -> None:
        """The MCP response should carry each record's status so clients can
        see the lifecycle state after a relaxed status filter."""
        record = _make_record(record_id="mem_archived", status=LifecycleStatus.ARCHIVED)
        result = MemorySearchResult(
            record=record,
            score=0.9,
            dense_score=0.7,
            sparse_score=0.0,
            graph_score=0.0,
            rank=1,
        )
        service = AsyncMock()
        service.search = AsyncMock(return_value=[result])

        with _patch_service(service):
            from metronix.mcp.tools.memory_search import metronix_memory_search

            out = await metronix_memory_search(
                query="hello",
                agent_id="agent-a",
                workspace_id="default",
                status=["all"],
            )

        assert "error" not in out
        assert out["results"][0]["record"]["status"] == "archived"
