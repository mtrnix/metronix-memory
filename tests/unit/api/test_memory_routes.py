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

from metronix.api.dependencies import get_memory_service
from metronix.api.routes.memory import router as memory_router
from metronix.auth.dependencies import get_current_user
from metronix.core.config import Settings
from metronix.core.exceptions import MemoryNotFoundError
from metronix.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    ReviewEntry,
    Role,
    User,
)
from metronix.memory.service import MemoryService

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METRONIX_ENV="development",
        AUTH_ENABLED=False,
        METRONIX_SECRET_KEY="test-secret",
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
    mock.count_records = AsyncMock(return_value=0)
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
        service.count_records = AsyncMock(return_value=1)

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
        assert body["total"] == 1
        assert body["limit"] == 10
        assert body["offset"] == 0
        assert body["has_more"] is False

        service.list_records.assert_awaited_once()
        kwargs = service.list_records.await_args.kwargs
        assert kwargs["agent_id"] == "agent-1"
        assert kwargs["scope"] == MemoryScope.PER_AGENT
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 0

        # count_records must receive the same filter surface as list_records.
        count_kwargs = service.count_records.await_args.kwargs
        assert count_kwargs["agent_id"] == "agent-1"
        assert count_kwargs["scope"] == MemoryScope.PER_AGENT

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
        assert body["total"] == 1
        service.list_session.assert_awaited_once_with("ws-test", "sess-1")
        service.list_records.assert_not_awaited()

    def test_list_pagination_has_more(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        service.list_records.return_value = [_sample_record(id=f"m{i}") for i in range(2)]
        service.count_records = AsyncMock(return_value=3)

        response = client.get(
            "/api/v1/memory/records",
            params={"limit": 2, "offset": 0},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["total"] == 3
        assert body["has_more"] is True
        assert len(body["records"]) == 2

    def test_list_total_respects_filters_last_page(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """Last page: offset + count == total → has_more=False, total unchanged."""
        service.list_records.return_value = [_sample_record(id="m-last")]
        service.count_records = AsyncMock(return_value=3)

        response = client.get(
            "/api/v1/memory/records",
            params={"limit": 2, "offset": 2},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["total"] == 3
        assert body["has_more"] is False


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
# PROJ-324: status field + status_filter
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PROJ-324: GET /records/{record_id}
# ---------------------------------------------------------------------------


class TestGetRecordById:
    def test_get_record_by_id_success(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """GET /records/{id} returns 200 with full MemoryRecordResponse."""
        stored = _sample_record(id="mem-get-1")
        service.get.return_value = stored

        response = client.get("/api/v1/memory/records/mem-get-1")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "mem-get-1"
        assert body["agent_id"] == "agent-1"
        assert "status" in body

    def test_get_record_by_id_404_when_missing(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """GET /records/{id} returns 404 when service.get returns None."""
        service.get.return_value = None

        response = client.get("/api/v1/memory/records/missing-id")

        assert response.status_code == 404

    def test_get_record_by_id_workspace_scoped(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """service.get must be called with workspace_id from JWT, not path."""
        stored = _sample_record(id="mem-1")
        service.get.return_value = stored

        client.get("/api/v1/memory/records/mem-1")

        service.get.assert_awaited_once()
        ws, rid = service.get.await_args.args
        assert ws == "ws-test"
        assert rid == "mem-1"

    def test_get_record_by_id_viewer_role_allowed(
        self,
        make_client: Callable[..., TestClient],
        service: AsyncMock,
    ) -> None:
        """Viewer role is sufficient for GET /records/{id}."""
        viewer_client = make_client(Role.VIEWER)
        stored = _sample_record(id="mem-1")
        service.get.return_value = stored

        response = viewer_client.get("/api/v1/memory/records/mem-1")
        assert response.status_code == 200


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


# ---------------------------------------------------------------------------
# PROJ-324: GET /memory/graph
# ---------------------------------------------------------------------------


class TestMemoryGraph:
    def test_memory_graph_uses_jwt_workspace(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """service.get_graph_neighborhood must be called with workspace_id from JWT."""
        seed = _sample_record(id="seed-1")
        service.get_graph_neighborhood.return_value = ([seed], [])

        response = client.get(
            "/api/v1/memory/graph",
            params={"seed_record_id": "seed-1", "depth": 1},
        )

        assert response.status_code == 200
        service.get_graph_neighborhood.assert_awaited_once()
        call_args = service.get_graph_neighborhood.await_args
        # First positional arg is workspace_id (from JWT), second is seed_record_id
        assert call_args.args[0] == "ws-test"
        assert call_args.args[1] == "seed-1"
        assert call_args.kwargs["depth"] == 1

    def test_memory_graph_depth_bounds(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """depth=0 and depth=4 are rejected with 422; depth=3 succeeds."""
        seed = _sample_record(id="seed-1")
        service.get_graph_neighborhood.return_value = ([seed], [])

        response_0 = client.get(
            "/api/v1/memory/graph",
            params={"seed_record_id": "seed-1", "depth": 0},
        )
        assert response_0.status_code == 422

        response_4 = client.get(
            "/api/v1/memory/graph",
            params={"seed_record_id": "seed-1", "depth": 4},
        )
        assert response_4.status_code == 422

        response_3 = client.get(
            "/api/v1/memory/graph",
            params={"seed_record_id": "seed-1", "depth": 3},
        )
        assert response_3.status_code == 200

    def test_memory_graph_neo4j_down_returns_seed_only(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """When service returns ([seed], []) (Neo4j down path), response has
        nodes=[seed] and edges=[]."""
        seed = _sample_record(id="seed-1")
        service.get_graph_neighborhood.return_value = ([seed], [])

        response = client.get(
            "/api/v1/memory/graph",
            params={"seed_record_id": "seed-1"},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["nodes"]) == 1
        assert body["nodes"][0]["id"] == "seed-1"
        assert body["edges"] == []

    def test_memory_graph_agent_id_filter(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """When agent_id query param is set, only records with matching agent_id survive."""
        rec_a = _sample_record(id="mem-a", agent_id="agent-x")
        rec_b = _sample_record(id="mem-b", agent_id="agent-y")
        edge_ab = {
            "source": "mem-a",
            "target": "mem-b",
            "type": "LINKED_TO",
            "metadata": None,
        }
        # Edge between a and c (both for agent-x)
        rec_c = _sample_record(id="mem-c", agent_id="agent-x")
        edge_ac = {
            "source": "mem-a",
            "target": "mem-c",
            "type": "LINKED_TO",
            "metadata": None,
        }
        service.get_graph_neighborhood.return_value = ([rec_a, rec_b, rec_c], [edge_ab, edge_ac])

        response = client.get(
            "/api/v1/memory/graph",
            params={"seed_record_id": "mem-a", "agent_id": "agent-x"},
        )

        assert response.status_code == 200
        body = response.json()
        node_ids = {n["id"] for n in body["nodes"]}
        assert "mem-a" in node_ids
        assert "mem-c" in node_ids
        assert "mem-b" not in node_ids  # agent-y filtered out
        # edge_ab is dropped (mem-b filtered out), edge_ac survives
        assert len(body["edges"]) == 1
        assert body["edges"][0]["source"] == "mem-a"
        assert body["edges"][0]["target"] == "mem-c"


# ---------------------------------------------------------------------------
# PROJ-324: GET /memory/review + POST /memory/review/{id}
# ---------------------------------------------------------------------------


def _sample_review_entry(**overrides: Any) -> ReviewEntry:
    defaults: dict[str, Any] = {
        "id": "rev-1",
        "workspace_id": "ws-test",
        "target_id": "mem-1",
        "target_kind": "memory_record",
        "reason": "possible_duplicate",
        "related_record_id": "mem-2",
        "content": "some content",
        "confidence": 0.85,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ReviewEntry(**defaults)


class TestReviewList:
    def test_review_list_pagination(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """Mock returns 5 entries with total=42 ⇒ count=5, total=42, has_more=True."""
        entries = [_sample_review_entry(id=f"rev-{i}") for i in range(5)]
        service.list_review_entries.return_value = (entries, 42)

        response = client.get(
            "/api/v1/memory/review",
            params={"limit": 5, "offset": 0},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 5
        assert body["total"] == 42
        assert body["has_more"] is True
        assert len(body["entries"]) == 5

    def test_review_list_503_when_freshness_store_missing(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """RuntimeError('freshness_store not configured') ⇒ 503."""
        service.list_review_entries.side_effect = RuntimeError("freshness_store not configured")

        response = client.get("/api/v1/memory/review")

        assert response.status_code == 503
        assert "Review queue" in response.json()["detail"]

    def test_review_list_reason_filter(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """reason query param is forwarded to service.list_review_entries."""
        service.list_review_entries.return_value = ([], 0)

        client.get(
            "/api/v1/memory/review",
            params={"reason": "possible_duplicate"},
        )

        service.list_review_entries.assert_awaited_once()
        call_kwargs = service.list_review_entries.await_args.kwargs
        assert call_kwargs["reason"] == "possible_duplicate"

    def test_review_list_viewer_only(
        self,
        make_client: Callable[..., TestClient],
        service: AsyncMock,
    ) -> None:
        """Viewer role is sufficient for GET /review."""
        viewer_client = make_client(Role.VIEWER)
        service.list_review_entries.return_value = ([], 0)

        response = viewer_client.get("/api/v1/memory/review")
        assert response.status_code == 200

    def test_review_list_has_more_false_when_last_page(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """has_more=False when offset + count >= total."""
        entries = [_sample_review_entry(id=f"rev-{i}") for i in range(3)]
        service.list_review_entries.return_value = (entries, 3)

        response = client.get(
            "/api/v1/memory/review",
            params={"limit": 20, "offset": 0},
        )

        assert response.status_code == 200
        assert response.json()["has_more"] is False


class TestReviewResolve:
    def test_review_resolve_keep(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """POST /review/{id} with action=keep ⇒ service.resolve_review, 204."""
        service.resolve_review.return_value = None  # return value unused by route

        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "keep"},
        )

        assert response.status_code == 204
        service.resolve_review.assert_awaited_once()
        call_kwargs = service.resolve_review.await_args.kwargs
        assert call_kwargs["action"] == "keep"
        assert call_kwargs["review_id"] == "rev-1"

    def test_review_resolve_merge_into(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """action=merge_into with target_record_id ⇒ service called with merge_into:<id>."""
        service.resolve_review.return_value = None

        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "merge_into", "target_record_id": "rec-2"},
        )

        assert response.status_code == 204
        call_kwargs = service.resolve_review.await_args.kwargs
        assert call_kwargs["action"] == "merge_into:rec-2"

    def test_review_resolve_merge_into_missing_target_422(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """action=merge_into without target_record_id ⇒ Pydantic 422."""
        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "merge_into"},
        )
        assert response.status_code == 422
        service.resolve_review.assert_not_awaited()

    def test_review_resolve_target_record_id_only_valid_for_merge(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """action=keep with target_record_id ⇒ 422 (only valid for merge_into)."""
        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "keep", "target_record_id": "rec-x"},
        )
        assert response.status_code == 422
        service.resolve_review.assert_not_awaited()

    def test_review_resolve_archive(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """action=archive ⇒ service called with action='archive', 204."""
        service.resolve_review.return_value = None

        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "archive"},
        )

        assert response.status_code == 204
        call_kwargs = service.resolve_review.await_args.kwargs
        assert call_kwargs["action"] == "archive"

    def test_review_resolve_discard(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """action=discard ⇒ 204."""
        service.resolve_review.return_value = None

        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "discard"},
        )

        assert response.status_code == 204
        call_kwargs = service.resolve_review.await_args.kwargs
        assert call_kwargs["action"] == "discard"

    def test_review_resolve_404_when_entry_missing(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """MemoryNotFoundError ⇒ 404."""
        service.resolve_review.side_effect = MemoryNotFoundError("review entry not found")

        response = client.post(
            "/api/v1/memory/review/missing-rev",
            json={"action": "keep"},
        )
        assert response.status_code == 404

    def test_review_resolve_400_on_invalid_action_value(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """Service raises ValueError ⇒ 400."""
        service.resolve_review.side_effect = ValueError("unknown action")

        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "keep"},
        )
        assert response.status_code == 400

    def test_review_resolve_passes_user_id_as_actor(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """service.resolve_review must receive actor=user.id (not 'mcp_caller')."""
        service.resolve_review.return_value = None

        client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "keep"},
        )

        call_kwargs = service.resolve_review.await_args.kwargs
        assert call_kwargs["actor"] == "u1"  # _make_user() uses id="u1"

    def test_review_resolve_requires_editor_role(
        self,
        make_client: Callable[..., TestClient],
        service: AsyncMock,
    ) -> None:
        """Viewer role is NOT sufficient for POST /review/{id} ⇒ 403."""
        viewer_client = make_client(Role.VIEWER)

        response = viewer_client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "keep"},
        )
        assert response.status_code == 403
        service.resolve_review.assert_not_awaited()

    def test_review_resolve_503_when_freshness_store_missing(
        self,
        client: TestClient,
        service: AsyncMock,
    ) -> None:
        """RuntimeError('freshness_store not configured') ⇒ 503."""
        service.resolve_review.side_effect = RuntimeError("freshness_store not configured")

        response = client.post(
            "/api/v1/memory/review/rev-1",
            json={"action": "keep"},
        )
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# ?workspace_id query scoping + access check (Control Center, family B)
# ---------------------------------------------------------------------------


class TestWorkspaceQueryScoping:
    def _client(
        self, *, workspace_ids: list[str], service: AsyncMock, settings: Settings
    ) -> TestClient:
        app = FastAPI()
        app.state.settings = settings
        app.include_router(memory_router, prefix="/api/v1")
        app.dependency_overrides[get_memory_service] = lambda: service
        app.dependency_overrides[get_current_user] = lambda: _make_user()

        @app.middleware("http")
        async def _inject(request, call_next):  # type: ignore[no-untyped-def]
            request.state.user = {"workspace_ids": workspace_ids}
            return await call_next(request)

        return TestClient(app, raise_server_exceptions=False)

    def test_search_scopes_to_requested_workspace_for_star_token(
        self, service: AsyncMock, settings: Settings
    ) -> None:
        service.search.return_value = []
        client = self._client(workspace_ids=["*"], service=service, settings=settings)

        resp = client.post(
            "/api/v1/memory/search?workspace_id=ws-x",
            json={"query": "hello"},
        )

        assert resp.status_code == 200
        passed_ws = service.search.await_args.args[0]
        assert passed_ws == "ws-x"

    def test_list_forbidden_for_non_member(self, service: AsyncMock, settings: Settings) -> None:
        client = self._client(workspace_ids=["ws-a"], service=service, settings=settings)

        resp = client.get("/api/v1/memory/records?workspace_id=ws-x")

        assert resp.status_code == 403
        service.list_records.assert_not_awaited()

    def test_list_without_param_uses_auth_derived(
        self, service: AsyncMock, settings: Settings
    ) -> None:
        service.list_records.return_value = []
        client = self._client(workspace_ids=["ws-a"], service=service, settings=settings)

        resp = client.get("/api/v1/memory/records")

        assert resp.status_code == 200
        assert service.list_records.await_args.args[0] == "ws-a"
