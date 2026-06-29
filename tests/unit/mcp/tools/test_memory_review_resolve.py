"""Unit tests for metronix_memory_review_resolve MCP tool (MTRNIX-314)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from metronix.core.exceptions import MemoryNotFoundError
from metronix.memory.resolution import ReviewResolution

if TYPE_CHECKING:
    from contextlib import AbstractContextManager


def _resolution(
    *,
    action: str = "keep",
    old_status: str = "review_needed",
    new_status: str = "active",
    superseded_by: str | None = None,
) -> ReviewResolution:
    return ReviewResolution(
        review_id="r1",
        target_id="mem001",
        action=action,
        old_status=old_status,
        new_status=new_status,
        superseded_by=superseded_by,
        machine_event_id="evt001",
    )


def _patch_service(service_mock: AsyncMock) -> AbstractContextManager[object]:
    return patch(
        "metronix.mcp.tools._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(return_value=service_mock),
    )


class TestActionKeep:
    async def test_keep_happy_path(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(return_value=_resolution(action="keep"))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1", action="keep", workspace_id="ws1"
            )

        assert "error" not in out
        assert out["success"] is True
        assert out["review_id"] == "r1"
        assert out["target_id"] == "mem001"
        assert out["action"] == "keep"
        assert out["old_status"] == "review_needed"
        assert out["new_status"] == "active"
        assert out["superseded_by"] is None
        assert out["machine_event_id"] == "evt001"


class TestActionArchive:
    async def test_archive_new_status(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(
            return_value=_resolution(action="archive", new_status="archived")
        )

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1", action="archive", workspace_id="ws1"
            )

        assert out["new_status"] == "archived"
        assert out["action"] == "archive"


class TestActionMerge:
    async def test_merge_into_sets_superseded_by(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(
            return_value=_resolution(
                action="merge_into",
                new_status="superseded",
                superseded_by="mem_target",
            )
        )

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1",
                action="merge_into:mem_target",
                workspace_id="ws1",
            )

        assert out["new_status"] == "superseded"
        assert out["superseded_by"] == "mem_target"

    async def test_merge_into_empty_target_invalid_params(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(
            side_effect=ValueError("merge_into: requires a target record id")
        )

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1", action="merge_into:", workspace_id="ws1"
            )

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"

    async def test_merge_into_missing_target_invalid_params(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(
            side_effect=ValueError("merge_into target mem_missing not found")
        )

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1",
                action="merge_into:mem_missing",
                workspace_id="ws1",
            )

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"


class TestActionDiscard:
    async def test_discard_soft_archives(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(
            return_value=_resolution(action="discard", new_status="archived")
        )

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1", action="discard", workspace_id="ws1"
            )

        assert out["new_status"] == "archived"
        assert out["action"] == "discard"


class TestErrors:
    async def test_unknown_action_invalid_params(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(side_effect=ValueError("Unknown action: bogus"))

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1", action="bogus", workspace_id="ws1"
            )

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"

    async def test_review_not_found_maps_to_document_not_found(self) -> None:
        service = AsyncMock()
        service.resolve_review = AsyncMock(
            side_effect=MemoryNotFoundError("Review entry r1 not found")
        )

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            out = await metronix_memory_review_resolve(
                review_id="r1", action="keep", workspace_id="ws1"
            )

        assert "error" in out
        assert out["error"]["code"] == "DOCUMENT_NOT_FOUND"

    async def test_missing_review_id_invalid_params(self) -> None:
        from metronix.mcp.tools.memory_review_resolve import (
            metronix_memory_review_resolve,
        )

        out = await metronix_memory_review_resolve(review_id="", action="keep", workspace_id="ws1")

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"

    async def test_missing_action_invalid_params(self) -> None:
        from metronix.mcp.tools.memory_review_resolve import (
            metronix_memory_review_resolve,
        )

        out = await metronix_memory_review_resolve(review_id="r1", action="", workspace_id="ws1")

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"

    async def test_idempotent_second_resolve_returns_not_found(self) -> None:
        """Spec: re-running the same resolve after the first succeeds -> 404.

        First call's side-effect: service.resolve_review returns resolution.
        Second call's side-effect: service raises MemoryNotFoundError because
        the review entry is gone.
        """
        service = AsyncMock()
        service.resolve_review = AsyncMock(
            side_effect=[
                _resolution(action="keep"),
                MemoryNotFoundError("Review entry r1 not found"),
            ]
        )

        with _patch_service(service):
            from metronix.mcp.tools.memory_review_resolve import (
                metronix_memory_review_resolve,
            )

            first = await metronix_memory_review_resolve(
                review_id="r1", action="keep", workspace_id="ws1"
            )
            second = await metronix_memory_review_resolve(
                review_id="r1", action="keep", workspace_id="ws1"
            )

        assert "error" not in first
        assert "error" in second
        assert second["error"]["code"] == "DOCUMENT_NOT_FOUND"
