"""Unit tests for ``metatron_memory_list`` status filter (MTRNIX-314)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from metatron.core.models import LifecycleStatus, MemoryRecord, MemoryScope

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
        "metatron.mcp.tools._memory_deps.build_memory_service_for_workspace",
        new=AsyncMock(return_value=service_mock),
    )


def _make_service() -> AsyncMock:
    service = AsyncMock()
    pg = MagicMock()
    pg.list_records = AsyncMock(return_value=[])
    pg.count_records = AsyncMock(return_value=0)
    service.pg_store = pg
    return service


class TestListStatusFilter:
    async def test_default_pushes_active_only_into_pg(self) -> None:
        service = _make_service()

        with _patch_service(service):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(agent_id="agent-a", workspace_id="default")

        assert "error" not in out
        lkw = service.pg_store.list_records.await_args.kwargs
        assert lkw["status"] == [LifecycleStatus.ACTIVE]
        ckw = service.pg_store.count_records.await_args.kwargs
        assert ckw["status"] == [LifecycleStatus.ACTIVE]

    async def test_all_sentinel_omits_status_filter(self) -> None:
        service = _make_service()

        with _patch_service(service):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(
                agent_id="agent-a", workspace_id="default", status=["all"]
            )

        assert "error" not in out
        assert service.pg_store.list_records.await_args.kwargs["status"] is None
        assert service.pg_store.count_records.await_args.kwargs["status"] is None

    async def test_include_set_passes_through(self) -> None:
        service = _make_service()

        with _patch_service(service):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(
                agent_id="agent-a",
                workspace_id="default",
                status=["active", "candidate"],
            )

        assert "error" not in out
        assert service.pg_store.list_records.await_args.kwargs["status"] == [
            LifecycleStatus.ACTIVE,
            LifecycleStatus.CANDIDATE,
        ]

    async def test_invalid_status_returns_invalid_params(self) -> None:
        service = _make_service()

        with _patch_service(service):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(
                agent_id="agent-a",
                workspace_id="default",
                status=["bogus"],
            )

        assert "error" in out
        assert out["error"]["code"] == "INVALID_PARAMS"
        service.pg_store.list_records.assert_not_called()

    async def test_total_reflects_filtered_count(self) -> None:
        service = _make_service()
        service.pg_store.list_records = AsyncMock(return_value=[_make_record("rec-1")])
        service.pg_store.count_records = AsyncMock(return_value=1)

        with _patch_service(service):
            from metatron.mcp.tools.memory_list import metatron_memory_list

            out = await metatron_memory_list(
                agent_id="agent-a",
                workspace_id="default",
                status=["active"],
            )

        assert out["total"] == 1
        assert out["count"] == 1
        assert out["records"][0]["status"] == "active"
