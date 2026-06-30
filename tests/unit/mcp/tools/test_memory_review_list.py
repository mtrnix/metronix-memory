"""Unit tests for metronix_memory_review_list MCP tool (MTRNIX-314)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from metronix.core.models import ReviewEntry

if TYPE_CHECKING:
    from contextlib import AbstractContextManager


def _review(
    review_id: str = "r1",
    target_id: str = "mem001",
    reason: str = "possible_duplicate",
) -> ReviewEntry:
    return ReviewEntry(
        id=review_id,
        workspace_id="ws1",
        target_id=target_id,
        target_kind="memory_record",
        reason=reason,
        related_record_id=None,
        content="dup preview",
        confidence=0.8,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
    )


def _patch_service(service_mock: AsyncMock) -> AbstractContextManager[object]:
    return patch(
        "metronix.mcp.tools._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(return_value=service_mock),
    )


class TestMemoryReviewList:
    async def test_happy_path(self) -> None:
        service = AsyncMock()
        service.list_review_entries = AsyncMock(return_value=([_review()], 1))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_list import (
                metronix_memory_review_list,
            )

            out = await metronix_memory_review_list(workspace_id="ws1")

        assert "error" not in out
        assert out["count"] == 1
        assert out["total"] == 1
        assert out["entries"][0]["id"] == "r1"
        assert out["entries"][0]["target_kind"] == "memory_record"
        assert out["entries"][0]["reason"] == "possible_duplicate"

    async def test_reason_filter_passed_through(self) -> None:
        service = AsyncMock()
        service.list_review_entries = AsyncMock(return_value=([], 0))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_list import (
                metronix_memory_review_list,
            )

            await metronix_memory_review_list(workspace_id="ws1", reason="possible_duplicate")

        kw = service.list_review_entries.await_args.kwargs
        assert kw["reason"] == "possible_duplicate"

    async def test_record_id_filter_passed_through(self) -> None:
        service = AsyncMock()
        service.list_review_entries = AsyncMock(return_value=([], 0))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_list import (
                metronix_memory_review_list,
            )

            await metronix_memory_review_list(workspace_id="ws1", record_id="mem_abc")

        kw = service.list_review_entries.await_args.kwargs
        assert kw["record_id"] == "mem_abc"

    async def test_default_workspace_used_when_missing(self) -> None:
        service = AsyncMock()
        service.list_review_entries = AsyncMock(return_value=([], 0))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_list import (
                metronix_memory_review_list,
            )

            await metronix_memory_review_list()

        # An omitted workspace resolves to the server default, not literal "default".
        from metronix.mcp.config import get_default_workspace_id

        assert service.list_review_entries.await_args.args[0] == get_default_workspace_id()

    async def test_service_failure_wrapped_in_internal_error(self) -> None:
        service = AsyncMock()
        service.list_review_entries = AsyncMock(side_effect=RuntimeError("boom"))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_list import (
                metronix_memory_review_list,
            )

            out = await metronix_memory_review_list(workspace_id="ws1")

        assert "error" in out
        assert out["error"]["code"] in {"INTERNAL_ERROR", "QDRANT_UNAVAILABLE"}

    async def test_pagination_bounds_clamped(self) -> None:
        service = AsyncMock()
        service.list_review_entries = AsyncMock(return_value=([], 0))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_list import (
                metronix_memory_review_list,
            )

            out = await metronix_memory_review_list(workspace_id="ws1", limit=500, offset=-3)

        assert "error" not in out
        # limit clamped to 100.
        kw = service.list_review_entries.await_args.kwargs
        assert kw["limit"] == 100
        assert kw["offset"] == 0
