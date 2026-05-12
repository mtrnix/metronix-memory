"""Unit tests for RawDocumentReadService (L3 read facade).

Tests verify that the service:
- Passes the bound workspace_id to both PG methods
- Propagates limit+offset correctly
- Returns the correct (records, total) tuple
- Fans out both PG calls concurrently via asyncio.gather
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from metatron.core.models import LifecycleStatus, RawDocument
from metatron.knowledge.service import RawDocumentReadService
from metatron.storage.postgres import PostgresStore


def _make_raw_doc(*, workspace_id: str = "ws-test", doc_id: str = "doc-1") -> RawDocument:
    return RawDocument(
        id=doc_id,
        workspace_id=workspace_id,
        connector_type="confluence",
        source_id="page-1",
        title="Test page",
        content="Hello world",
        status=LifecycleStatus.ACTIVE,
        freshness_score=0.5,
    )


@pytest.fixture
def pg_store() -> AsyncMock:
    mock = AsyncMock(spec=PostgresStore)
    return mock


@pytest.fixture
def service(pg_store: AsyncMock) -> RawDocumentReadService:
    return RawDocumentReadService(pg_store, workspace_id="ws-test")


# ---------------------------------------------------------------------------
# RDR1 — workspace_id is forwarded to list_raw_documents
# ---------------------------------------------------------------------------


class TestWorkspaceBinding:
    async def test_list_passes_bound_workspace_id(
        self,
        service: RawDocumentReadService,
        pg_store: AsyncMock,
    ) -> None:
        pg_store.list_raw_documents.return_value = []
        pg_store.count_raw_documents.return_value = 0

        await service.list_records(limit=50, offset=0)

        pg_store.list_raw_documents.assert_awaited_once_with(
            "ws-test",
            limit=50,
            offset=0,
        )

    async def test_count_passes_bound_workspace_id(
        self,
        service: RawDocumentReadService,
        pg_store: AsyncMock,
    ) -> None:
        pg_store.list_raw_documents.return_value = []
        pg_store.count_raw_documents.return_value = 7

        await service.list_records(limit=50, offset=0)

        pg_store.count_raw_documents.assert_awaited_once_with("ws-test")


# ---------------------------------------------------------------------------
# RDR2 — returns (records, total) tuple
# ---------------------------------------------------------------------------


class TestReturnShape:
    async def test_returns_records_and_total(
        self,
        service: RawDocumentReadService,
        pg_store: AsyncMock,
    ) -> None:
        doc = _make_raw_doc()
        pg_store.list_raw_documents.return_value = [doc]
        pg_store.count_raw_documents.return_value = 42

        records, total = await service.list_records()

        assert len(records) == 1
        assert records[0].id == "doc-1"
        assert total == 42

    async def test_empty_workspace(
        self,
        service: RawDocumentReadService,
        pg_store: AsyncMock,
    ) -> None:
        pg_store.list_raw_documents.return_value = []
        pg_store.count_raw_documents.return_value = 0

        records, total = await service.list_records()

        assert records == []
        assert total == 0


# ---------------------------------------------------------------------------
# RDR3 — pagination propagates
# ---------------------------------------------------------------------------


class TestPagination:
    async def test_limit_and_offset_propagate(
        self,
        service: RawDocumentReadService,
        pg_store: AsyncMock,
    ) -> None:
        pg_store.list_raw_documents.return_value = []
        pg_store.count_raw_documents.return_value = 100

        await service.list_records(limit=5, offset=10)

        pg_store.list_raw_documents.assert_awaited_once_with(
            "ws-test",
            limit=5,
            offset=10,
        )

    async def test_default_pagination(
        self,
        service: RawDocumentReadService,
        pg_store: AsyncMock,
    ) -> None:
        pg_store.list_raw_documents.return_value = []
        pg_store.count_raw_documents.return_value = 0

        await service.list_records()

        pg_store.list_raw_documents.assert_awaited_once_with(
            "ws-test",
            limit=50,
            offset=0,
        )


# ---------------------------------------------------------------------------
# RDR4 — both PG calls are awaited (concurrent fan-out smoke test)
# ---------------------------------------------------------------------------


class TestConcurrentFanOut:
    async def test_both_pg_calls_are_awaited(
        self,
        service: RawDocumentReadService,
        pg_store: AsyncMock,
    ) -> None:
        pg_store.list_raw_documents.return_value = [_make_raw_doc()]
        pg_store.count_raw_documents.return_value = 1

        await service.list_records(limit=10, offset=0)

        assert pg_store.list_raw_documents.await_count == 1
        assert pg_store.count_raw_documents.await_count == 1
