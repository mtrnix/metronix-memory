"""Tests for /api/v1/memory routes.

Uses FastAPI TestClient with dependency overrides so the routes exercise the
full request/response stack without touching real stores. Full CRUD cycle
test at the bottom doubles as the integration test required by the DoD.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.api.dependencies import get_memory_service
from metatron.api.routes.memory import router as memory_router
from metatron.auth.dependencies import get_current_user
from metatron.core.config import Settings
from metatron.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    Role,
    User,
)
from metatron.memory.service import MemoryService

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=False,
        METATRON_SECRET_KEY="test-secret",
    )


def _make_user(role: Role = Role.EDITOR) -> User:
    return User(
        id="u1",
        username="tester",
        email="t@example.com",
        role=role,
        workspace_ids=["ws-test"],
    )


def _sample_record(**overrides: Any) -> MemoryRecord:
    defaults: dict[str, Any] = {
        "id": "mem-1",
        "workspace_id": "ws-test",
        "agent_id": "agent-1",
        "scope": MemoryScope.PER_AGENT,
        "source_type": "conversation",
        "content": "prefers dark mode",
        "tags": ["preference"],
        "importance_score": 0.75,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


@pytest.fixture
def service() -> AsyncMock:
    """An AsyncMock MemoryService for dependency override."""
    mock = AsyncMock(spec=MemoryService)
    return mock


@pytest.fixture
def make_client(
    settings: Settings,
    service: AsyncMock,
) -> Callable[..., TestClient]:
    """Factory producing a minimal app TestClient with configurable user role.

    Uses a minimal FastAPI app with only the memory router to avoid pulling in
    the enterprise plugin's auth middleware — dependency overrides on
    ``get_current_user`` are enough to simulate an authenticated request.
    """

    def _factory(role: Role = Role.EDITOR) -> TestClient:
        app = FastAPI()
        app.state.settings = settings
        app.include_router(memory_router, prefix="/api/v1")
        app.dependency_overrides[get_memory_service] = lambda: service
        app.dependency_overrides[get_current_user] = lambda: _make_user(role=role)

        @app.middleware("http")
        async def _inject_user(request, call_next):  # type: ignore[no-untyped-def]
            request.state.user = {"workspace_ids": ["ws-test"]}
            return await call_next(request)

        return TestClient(app, raise_server_exceptions=False)

    return _factory


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client(Role.EDITOR)


# ---------------------------------------------------------------------------
# POST /records
# ---------------------------------------------------------------------------


class TestCreateRecord:
    def test_create_record_201(self, client: TestClient, service: AsyncMock) -> None:
        stored = _sample_record(scope=MemoryScope.PER_AGENT)
        service.save.return_value = stored

        response = client.post(
            "/api/v1/memory/records",
            json={
                "content": "prefers dark mode",
                "agent_id": "agent-1",
                "scope": "per_agent",
                "tags": ["preference"],
                "importance_score": 0.75,
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["id"] == "mem-1"
        assert body["scope"] == "per_agent"
        assert body["agent_id"] == "agent-1"
        service.save.assert_awaited_once()
        saved_ws, saved_record = service.save.await_args.args
        assert saved_ws == "ws-test"
        assert saved_record.workspace_id == "ws-test"
        assert saved_record.content == "prefers dark mode"

    def test_create_record_session_scope_requires_session_id(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        response = client.post(
            "/api/v1/memory/records",
            json={
                "content": "transient note",
                "agent_id": "agent-1",
                "scope": "session",
            },
        )

        assert response.status_code == 422
        service.save.assert_not_awaited()
        service.cache_session.assert_not_awaited()

    def test_create_record_session_scope_calls_cache_session(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        stored = _sample_record(scope=MemoryScope.SESSION, session_id="sess-1")
        service.cache_session.return_value = stored

        response = client.post(
            "/api/v1/memory/records",
            json={
                "content": "transient note",
                "agent_id": "agent-1",
                "scope": "session",
                "session_id": "sess-1",
            },
        )

        assert response.status_code == 201
        service.cache_session.assert_awaited_once()
        ws, session, record = service.cache_session.await_args.args
        assert ws == "ws-test"
        assert session == "sess-1"
        assert record.session_id == "sess-1"
        service.save.assert_not_awaited()

    def test_create_record_viewer_forbidden(
        self,
        make_client: Callable[..., TestClient],
        service: AsyncMock,
    ) -> None:
        client = make_client(Role.VIEWER)
        response = client.post(
            "/api/v1/memory/records",
            json={
                "content": "x",
                "agent_id": "agent-1",
            },
        )
        assert response.status_code == 403
        service.save.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_200(self, client: TestClient, service: AsyncMock) -> None:
        r1 = MemorySearchResult(
            record=_sample_record(id="m1"),
            score=0.9,
            dense_score=0.8,
            sparse_score=0.0,
            graph_score=0.5,
            rank=1,
        )
        r2 = MemorySearchResult(
            record=_sample_record(id="m2"),
            score=0.7,
            dense_score=0.6,
            sparse_score=0.0,
            graph_score=0.3,
            rank=2,
        )
        service.search.return_value = [r1, r2]

        response = client.post(
            "/api/v1/memory/search",
            json={"query": "dark mode", "top_k": 5},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert len(body["results"]) == 2
        assert body["results"][0]["record"]["id"] == "m1"
        service.search.assert_awaited_once()

    def test_search_empty_query_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/memory/search",
            json={"query": ""},
        )
        assert response.status_code == 422

    def test_search_search_not_configured_503(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        service.search.side_effect = RuntimeError("search not configured")

        response = client.post(
            "/api/v1/memory/search",
            json={"query": "anything"},
        )
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /records
# ---------------------------------------------------------------------------


class TestListRecords:
    def test_list_records_with_filters(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        service.list_records.return_value = [_sample_record(id="m1")]

        response = client.get(
            "/api/v1/memory/records",
            params={
                "agent_id": "agent-1",
                "scope": "per_agent",
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["limit"] == 10
        assert body["offset"] == 0
        assert body["has_more"] is False

        service.list_records.assert_awaited_once()
        kwargs = service.list_records.await_args.kwargs
        assert kwargs["agent_id"] == "agent-1"
        assert kwargs["scope"] == MemoryScope.PER_AGENT
        assert kwargs["limit"] == 11  # limit + 1 for has_more detection
        assert kwargs["offset"] == 0

    def test_list_records_session_branch(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        service.list_session.return_value = [
            _sample_record(id="s1", scope=MemoryScope.SESSION, session_id="sess-1"),
        ]

        response = client.get(
            "/api/v1/memory/records",
            params={
                "session_id": "sess-1",
                "agent_id": "ignored",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        service.list_session.assert_awaited_once_with("ws-test", "sess-1")
        service.list_records.assert_not_awaited()

    def test_list_pagination_has_more(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        service.list_records.return_value = [_sample_record(id=f"m{i}") for i in range(3)]

        response = client.get(
            "/api/v1/memory/records",
            params={"limit": 2, "offset": 0},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["has_more"] is True
        assert len(body["records"]) == 2


# ---------------------------------------------------------------------------
# DELETE /records/{record_id}
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_204(self, client: TestClient, service: AsyncMock) -> None:
        service.delete.return_value = True

        response = client.delete("/api/v1/memory/records/r1")

        assert response.status_code == 204
        assert response.content == b""
        service.delete.assert_awaited_once()

    def test_delete_404(self, client: TestClient, service: AsyncMock) -> None:
        service.delete.return_value = False

        response = client.delete("/api/v1/memory/records/r1")
        assert response.status_code == 404

    def test_delete_qdrant_failure_500(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        service.delete.side_effect = RuntimeError("qdrant boom")

        response = client.delete("/api/v1/memory/records/r1")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Full CRUD cycle (integration-style)
# ---------------------------------------------------------------------------


class TestMemoryCRUDCycle:
    def test_create_search_list_delete(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        stored = _sample_record(id="mem-cycle", scope=MemoryScope.PER_AGENT)
        service.save.return_value = stored
        service.list_records.return_value = [stored]
        service.search.return_value = [
            MemorySearchResult(
                record=stored,
                score=0.9,
                dense_score=0.8,
                sparse_score=0.0,
                graph_score=0.3,
                rank=1,
            ),
        ]
        service.delete.return_value = True

        # CREATE
        create = client.post(
            "/api/v1/memory/records",
            json={
                "content": stored.content,
                "agent_id": stored.agent_id,
                "tags": list(stored.tags),
                "importance_score": stored.importance_score,
            },
        )
        assert create.status_code == 201
        created = create.json()
        assert created["id"] == "mem-cycle"

        # SEARCH
        search = client.post(
            "/api/v1/memory/search",
            json={"query": stored.content},
        )
        assert search.status_code == 200
        search_body = search.json()
        assert search_body["count"] == 1
        assert search_body["results"][0]["record"]["id"] == "mem-cycle"

        # LIST
        listing = client.get("/api/v1/memory/records")
        assert listing.status_code == 200
        listing_body = listing.json()
        assert listing_body["count"] == 1
        assert listing_body["records"][0]["id"] == "mem-cycle"

        # DELETE
        delete = client.delete("/api/v1/memory/records/mem-cycle")
        assert delete.status_code == 204
        service.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# MTRNIX-324: status field + status_filter
# ---------------------------------------------------------------------------


class TestStatusField:
    def test_response_includes_status_field_active_default(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """Response must carry status='active' for a default-status record."""
        stored = _sample_record()  # status defaults to ACTIVE
        service.save.return_value = stored

        response = client.post(
            "/api/v1/memory/records",
            json={"content": "x", "agent_id": "agent-1"},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "active"

    def test_response_includes_status_field_archived(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """Records with ARCHIVED status round-trip to 'archived'."""
        stored = _sample_record(status=LifecycleStatus.ARCHIVED)
        service.save.return_value = stored

        response = client.post(
            "/api/v1/memory/records",
            json={"content": "x", "agent_id": "agent-1"},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "archived"


class TestSearchStatusFilter:
    def test_search_default_excludes_archived_and_superseded(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """POST /search without status_filter calls service with all statuses
        EXCEPT ARCHIVED and SUPERSEDED."""
        service.search.return_value = []

        client.post("/api/v1/memory/search", json={"query": "test"})

        service.search.assert_awaited_once()
        call_kwargs = service.search.await_args.kwargs
        assert "status_filter" in call_kwargs
        effective = set(call_kwargs["status_filter"])
        assert LifecycleStatus.ARCHIVED not in effective
        assert LifecycleStatus.SUPERSEDED not in effective
        # All other statuses should be present
        for status in LifecycleStatus:
            if status not in (LifecycleStatus.ARCHIVED, LifecycleStatus.SUPERSEDED):
                assert status in effective

    def test_search_explicit_status_filter_overrides_default(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """POST /search with explicit status_filter passes it through unchanged."""
        service.search.return_value = []

        client.post(
            "/api/v1/memory/search",
            json={"query": "test", "status_filter": ["archived"]},
        )

        service.search.assert_awaited_once()
        call_kwargs = service.search.await_args.kwargs
        assert call_kwargs["status_filter"] == [LifecycleStatus.ARCHIVED]

    def test_search_status_filter_invalid_value_422(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """Non-enum status_filter value is rejected by Pydantic as 422."""
        response = client.post(
            "/api/v1/memory/search",
            json={"query": "test", "status_filter": ["all"]},
        )
        # "all" is an MCP-only sentinel; REST rejects it with 422
        assert response.status_code == 422
        service.search.assert_not_awaited()


class TestListStatusFilter:
    def test_list_records_status_filter_pushes_through(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """GET /records?status_filter=active&status_filter=stale pushes through."""
        service.list_records.return_value = []

        client.get(
            "/api/v1/memory/records",
            params={"status_filter": ["active", "stale"]},
        )

        service.list_records.assert_awaited_once()
        call_kwargs = service.list_records.await_args.kwargs
        assert set(call_kwargs["status"]) == {LifecycleStatus.ACTIVE, LifecycleStatus.STALE}

    def test_list_records_default_no_status_filter(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """GET /records without status_filter calls service with status=None."""
        service.list_records.return_value = []

        client.get("/api/v1/memory/records")

        service.list_records.assert_awaited_once()
        call_kwargs = service.list_records.await_args.kwargs
        assert call_kwargs["status"] is None
