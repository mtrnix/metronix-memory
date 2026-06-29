"""Tests for GET /api/v1/knowledge/records.

Uses a minimal FastAPI app with dependency overrides so the route exercises
the full request/response stack without touching real stores.

Scenarios mirror the test plan in the Phase 1 plan doc §6.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metronix.api.dependencies import get_memory_service, get_raw_document_service
from metronix.api.routes.knowledge import router as knowledge_router
from metronix.auth.dependencies import get_current_user
from metronix.core.config import Settings
from metronix.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    RawDocument,
    Role,
    User,
)
from metronix.knowledge.service import RawDocumentReadService  # noqa: TC001
from metronix.memory.service import MemoryService  # noqa: TC001

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user(role: Role = Role.VIEWER) -> User:
    return User(
        id="u1",
        username="tester",
        email="t@example.com",
        role=role,
        workspace_ids=["ws-test"],
    )


def _sample_mem_record(**overrides: Any) -> MemoryRecord:
    defaults: dict[str, Any] = {
        "id": "mem-1",
        "workspace_id": "ws-test",
        "agent_id": "agent-1",
        "scope": MemoryScope.PER_AGENT,
        "source_type": "conversation",
        "content": "user prefers dark mode",
        "tags": ["preference"],
        "importance_score": 0.75,
        "status": LifecycleStatus.ACTIVE,
        "freshness_score": 0.8,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def _sample_raw_doc(**overrides: Any) -> RawDocument:
    defaults: dict[str, Any] = {
        "id": "doc-1",
        "workspace_id": "ws-test",
        "connector_type": "confluence",
        "source_id": "page-1",
        "title": "Engineering Wiki",
        "content": "We use Python 3.12",
        "status": LifecycleStatus.ACTIVE,
        "freshness_score": 0.5,
        "updated_at": datetime(2026, 1, 3, tzinfo=UTC),
        "metadata": {},
    }
    defaults.update(overrides)
    return RawDocument(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(
        METRONIX_ENV="development",
        AUTH_ENABLED=False,
        METRONIX_SECRET_KEY="test-secret",
    )


@pytest.fixture
def mem_service() -> MagicMock:
    """MemoryService mock (list_records + count_records pair)."""
    mock = MagicMock(spec=MemoryService)
    mock.list_records = AsyncMock(return_value=[])
    mock.count_records = AsyncMock(return_value=0)
    return mock


@pytest.fixture
def raw_doc_service() -> AsyncMock:
    mock = AsyncMock(spec=RawDocumentReadService)
    mock.list_records = AsyncMock(return_value=([], 0))
    return mock


def _make_client(
    settings: Settings,
    mem_service: MagicMock,
    raw_doc_service: AsyncMock,
    role: Role = Role.VIEWER,
) -> TestClient:
    """Minimal FastAPI app with only the knowledge router wired."""
    app = FastAPI()
    app.state.settings = settings
    app.include_router(knowledge_router, prefix="/api/v1")
    app.dependency_overrides[get_memory_service] = lambda: mem_service
    app.dependency_overrides[get_raw_document_service] = lambda: raw_doc_service
    app.dependency_overrides[get_current_user] = lambda: _make_user(role=role)

    @app.middleware("http")
    async def _inject_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user = {"workspace_ids": ["ws-test"]}
        return await call_next(request)

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(
    settings: Settings,
    mem_service: MagicMock,
    raw_doc_service: AsyncMock,
) -> TestClient:
    return _make_client(settings, mem_service, raw_doc_service)


# ---------------------------------------------------------------------------
# T1 — Empty workspace, origin=all
# ---------------------------------------------------------------------------


class TestEmptyWorkspace:
    def test_empty_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/knowledge/records?origin=all")
        assert resp.status_code == 200
        body = resp.json()
        assert body["records"] == []
        assert body["count"] == 0
        assert body["total"] == 0
        assert body["has_more"] is False
        assert body["partial"] is False
        assert body["failed_sources"] == []


# ---------------------------------------------------------------------------
# T2 — Agent-only data, origin=all
# ---------------------------------------------------------------------------


class TestAgentOnlyData:
    def test_agent_rows_have_correct_origin(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        record = _sample_mem_record()
        mem_service.list_records = AsyncMock(return_value=[record])
        mem_service.count_records = AsyncMock(return_value=1)
        raw_doc_service.list_records = AsyncMock(return_value=([], 0))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["records"]) == 1
        assert body["records"][0]["origin"] == "agent"

    def test_sort_order_by_updated_at_desc(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        older = _sample_mem_record(id="old", updated_at=datetime(2025, 1, 1, tzinfo=UTC))
        newer = _sample_mem_record(id="new", updated_at=datetime(2026, 6, 1, tzinfo=UTC))
        mem_service.list_records = AsyncMock(return_value=[older, newer])
        mem_service.count_records = AsyncMock(return_value=2)
        raw_doc_service.list_records = AsyncMock(return_value=([], 0))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records")
        body = resp.json()
        ids = [r["id"] for r in body["records"]]
        assert ids[0] == "new"
        assert ids[1] == "old"


# ---------------------------------------------------------------------------
# T3 — KB-only data, origin=all
# ---------------------------------------------------------------------------


class TestKbOnlyData:
    def test_kb_rows_have_correct_shape(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        doc = _sample_raw_doc()
        mem_service.list_records = AsyncMock(return_value=[])
        mem_service.count_records = AsyncMock(return_value=0)
        raw_doc_service.list_records = AsyncMock(return_value=([doc], 1))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all")
        body = resp.json()
        assert len(body["records"]) == 1
        rec = body["records"][0]
        assert rec["origin"] == "kb"
        assert rec["agent_id"] is None
        assert rec["tags"] == []

    def test_kb_row_source_type_from_connector_type(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """T17 — RawDocument.connector_type appears as source_type."""
        doc = _sample_raw_doc(connector_type="confluence")
        mem_service.list_records = AsyncMock(return_value=[])
        mem_service.count_records = AsyncMock(return_value=0)
        raw_doc_service.list_records = AsyncMock(return_value=([doc], 1))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all")
        body = resp.json()
        assert body["records"][0]["source_type"] == "confluence"


# ---------------------------------------------------------------------------
# T4 — Both sources populated, origin=all
# ---------------------------------------------------------------------------


class TestBothSources:
    def test_combined_pagination_math(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        mem_records = [_sample_mem_record(id=f"m{i}") for i in range(3)]
        kb_docs = [_sample_raw_doc(id=f"d{i}") for i in range(2)]
        mem_service.list_records = AsyncMock(return_value=mem_records)
        mem_service.count_records = AsyncMock(return_value=3)
        raw_doc_service.list_records = AsyncMock(return_value=(kb_docs, 2))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?limit=10")
        body = resp.json()
        assert len(body["records"]) == 5  # 3 + 2
        # total from both legs
        assert body["total"] == 5
        # has_more = (0 + 10) < (3 + 2) = 10 < 5 = False
        assert body["has_more"] is False

    def test_has_more_true_when_total_exceeds_page(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        mem_records = [_sample_mem_record(id=f"m{i}") for i in range(3)]
        kb_docs = [_sample_raw_doc(id=f"d{i}") for i in range(3)]
        # total = 100 + 200 = 300; offset=0; limit=5 → has_more=True
        mem_service.list_records = AsyncMock(return_value=mem_records)
        mem_service.count_records = AsyncMock(return_value=100)
        raw_doc_service.list_records = AsyncMock(return_value=(kb_docs, 200))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?limit=5")
        body = resp.json()
        assert body["total"] == 300
        assert body["has_more"] is True


# ---------------------------------------------------------------------------
# T5 — origin=agent filter
# ---------------------------------------------------------------------------


class TestOriginAgentFilter:
    def test_only_agent_leg_called(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        mem_service.list_records = AsyncMock(return_value=[_sample_mem_record()])
        mem_service.count_records = AsyncMock(return_value=1)
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=agent")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["records"]) == 1
        assert body["records"][0]["origin"] == "agent"
        assert body["total"] == 1
        # KB service was NOT called
        raw_doc_service.list_records.assert_not_awaited()


# ---------------------------------------------------------------------------
# T6 — origin=kb filter
# ---------------------------------------------------------------------------


class TestOriginKbFilter:
    def test_only_kb_leg_called(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        raw_doc_service.list_records = AsyncMock(return_value=([_sample_raw_doc()], 1))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=kb")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["records"]) == 1
        assert body["records"][0]["origin"] == "kb"
        assert body["total"] == 1
        # Memory service list_records was NOT called
        mem_service.list_records.assert_not_awaited()


# ---------------------------------------------------------------------------
# T7 — Pagination propagation
# ---------------------------------------------------------------------------


class TestPagination:
    def test_origin_all_legs_overfetch_full_window(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """origin=all: each leg fetches [0, offset+limit) so the merged page is exact."""
        mem_service.list_records = AsyncMock(return_value=[])
        mem_service.count_records = AsyncMock(return_value=0)
        raw_doc_service.list_records = AsyncMock(return_value=([], 0))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?limit=10&offset=20")
        assert resp.status_code == 200
        mem_service.list_records.assert_awaited_once()
        call_kwargs = mem_service.list_records.await_args
        assert call_kwargs[1]["limit"] == 30  # offset + limit
        assert call_kwargs[1]["offset"] == 0

        raw_doc_service.list_records.assert_awaited_once_with(limit=30, offset=0)

    def test_single_origin_forwards_limit_offset_unchanged(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """origin=agent: pagination pushes down to the source — no over-fetch."""
        mem_service.list_records = AsyncMock(return_value=[])
        mem_service.count_records = AsyncMock(return_value=0)
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=agent&limit=10&offset=20")
        assert resp.status_code == 200
        call_kwargs = mem_service.list_records.await_args
        assert call_kwargs[1]["limit"] == 10
        assert call_kwargs[1]["offset"] == 20

    def test_origin_all_offset_slices_exact_global_page(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """Page 2 of the merged view contains the true global tail, not per-leg offsets."""
        mem_records = [
            _sample_mem_record(id="m-new", updated_at=datetime(2026, 4, 1, tzinfo=UTC)),
            _sample_mem_record(id="m-old", updated_at=datetime(2026, 1, 1, tzinfo=UTC)),
        ]
        kb_docs = [
            _sample_raw_doc(id="d-new", updated_at=datetime(2026, 3, 1, tzinfo=UTC)),
            _sample_raw_doc(id="d-old", updated_at=datetime(2026, 2, 1, tzinfo=UTC)),
        ]
        mem_service.list_records = AsyncMock(return_value=mem_records)
        mem_service.count_records = AsyncMock(return_value=2)
        raw_doc_service.list_records = AsyncMock(return_value=(kb_docs, 2))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all&limit=2&offset=2")
        assert resp.status_code == 200
        body = resp.json()
        # Global order: m-new(04) > d-new(03) > d-old(02) > m-old(01); page 2 = tail.
        assert [r["id"] for r in body["records"]] == ["d-old", "m-old"]
        assert body["count"] == 2
        assert body["total"] == 4
        assert body["has_more"] is False

    def test_origin_all_offset_past_total_is_empty_not_infinite(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """offset >= total: empty page, has_more=False (no infinite-next loop)."""
        mem_service.list_records = AsyncMock(return_value=[_sample_mem_record(id="m1")])
        mem_service.count_records = AsyncMock(return_value=1)
        raw_doc_service.list_records = AsyncMock(return_value=([], 0))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all&limit=50&offset=50")
        assert resp.status_code == 200
        body = resp.json()
        assert body["records"] == []
        assert body["count"] == 0
        assert body["total"] == 1
        assert body["has_more"] is False


# ---------------------------------------------------------------------------
# T8 — Memory leg raises in origin=all
# ---------------------------------------------------------------------------


class TestPartialFailureAgentLeg:
    def test_agent_leg_failure_returns_partial(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        mem_service.list_records = AsyncMock(side_effect=RuntimeError("PG down"))
        mem_service.count_records = AsyncMock(side_effect=RuntimeError("PG down"))
        doc = _sample_raw_doc()
        raw_doc_service.list_records = AsyncMock(return_value=([doc], 1))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all")
        assert resp.status_code == 200
        body = resp.json()
        assert body["partial"] is True
        assert "agent" in body["failed_sources"]
        assert len(body["records"]) == 1
        assert body["records"][0]["origin"] == "kb"
        # total covers only the surviving source (failed leg contributes 0)
        assert body["total"] == 1


# ---------------------------------------------------------------------------
# T9 — KB leg raises in origin=all
# ---------------------------------------------------------------------------


class TestPartialFailureKbLeg:
    def test_kb_leg_failure_returns_partial(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        record = _sample_mem_record()
        mem_service.list_records = AsyncMock(return_value=[record])
        mem_service.count_records = AsyncMock(return_value=1)
        raw_doc_service.list_records = AsyncMock(side_effect=RuntimeError("Qdrant timeout"))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all")
        assert resp.status_code == 200
        body = resp.json()
        assert body["partial"] is True
        assert "kb" in body["failed_sources"]
        assert len(body["records"]) == 1
        assert body["records"][0]["origin"] == "agent"


# ---------------------------------------------------------------------------
# T10 — Both legs raise in origin=all → 503
# ---------------------------------------------------------------------------


class TestBothLegsFailure:
    def test_both_legs_fail_returns_503(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        mem_service.list_records = AsyncMock(side_effect=RuntimeError("PG down"))
        mem_service.count_records = AsyncMock(side_effect=RuntimeError("PG down"))
        raw_doc_service.list_records = AsyncMock(side_effect=RuntimeError("KB down"))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=all")
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# T11 — Single leg requested and raises → 503
# ---------------------------------------------------------------------------


class TestSingleLegFailure:
    def test_agent_leg_requested_and_fails_503(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        mem_service.list_records = AsyncMock(side_effect=RuntimeError("PG down"))
        mem_service.count_records = AsyncMock(side_effect=RuntimeError("PG down"))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=agent")
        assert resp.status_code == 503

    def test_kb_leg_requested_and_fails_503(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        raw_doc_service.list_records = AsyncMock(side_effect=RuntimeError("PG down"))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=kb")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# T12 — Workspace isolation (mock-based)
# ---------------------------------------------------------------------------


class TestWorkspaceIsolation:
    def test_workspace_id_passed_from_auth(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """The workspace_id passed to the service must match the auth-derived value."""
        mem_service.list_records = AsyncMock(return_value=[])
        mem_service.count_records = AsyncMock(return_value=0)
        raw_doc_service.list_records = AsyncMock(return_value=([], 0))
        client = _make_client(settings, mem_service, raw_doc_service)

        client.get("/api/v1/knowledge/records?origin=agent")

        # The workspace_id injected by the middleware is "ws-test"
        mem_service.list_records.assert_awaited_once()
        args, kwargs = mem_service.list_records.await_args
        # positional first arg is workspace_id
        assert args[0] == "ws-test"


# ---------------------------------------------------------------------------
# T13 / T14 — RBAC
# ---------------------------------------------------------------------------


class TestRbac:
    def test_viewer_role_succeeds(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        client = _make_client(settings, mem_service, raw_doc_service, role=Role.VIEWER)
        resp = client.get("/api/v1/knowledge/records")
        assert resp.status_code == 200

    def test_auth_disabled_returns_200(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """With AUTH_ENABLED=false, no credentials → still 200 (mirrors memory routes)."""
        # The factory already uses AUTH_ENABLED=False settings
        client = _make_client(settings, mem_service, raw_doc_service)
        resp = client.get("/api/v1/knowledge/records")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# T15 — limit/offset validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_limit_zero_is_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/knowledge/records?limit=0")
        assert resp.status_code == 422

    def test_limit_over_200_is_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/knowledge/records?limit=201")
        assert resp.status_code == 422

    def test_negative_offset_is_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/knowledge/records?offset=-1")
        assert resp.status_code == 422

    def test_offset_over_10000_is_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/knowledge/records?offset=10001")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# T16 — origin validation
# ---------------------------------------------------------------------------


class TestOriginValidation:
    def test_invalid_origin_is_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/knowledge/records?origin=invalid")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# T17 — KB source_type ↔ connector_type mapping (covered in TestKbOnlyData)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T18 — updated_at round-trip (ISO 8601, offset-aware)
# ---------------------------------------------------------------------------


class TestDatetimeSerialization:
    def test_updated_at_is_iso8601(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        doc = _sample_raw_doc(updated_at=datetime(2026, 3, 14, 9, 26, 53, tzinfo=UTC))
        raw_doc_service.list_records = AsyncMock(return_value=([doc], 1))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=kb")
        body = resp.json()
        assert body["records"][0]["updated_at"] == "2026-03-14T09:26:53Z"


# ---------------------------------------------------------------------------
# Phase 2 — lifetime filter tests (K1–K7)
# ---------------------------------------------------------------------------


class TestLifetimeFilter:
    """K1 — default request passes lifetime=persistent to memory service."""

    def test_k1_default_passes_persistent_to_service(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        client = _make_client(settings, mem_service, raw_doc_service)
        client.get("/api/v1/knowledge/records?origin=agent")

        _, call_kwargs = mem_service.list_records.await_args
        assert call_kwargs["lifetime"] == "persistent"

    def test_k2_lifetime_session_passed_to_service(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """K2 — ?lifetime=session forwards 'session' to memory_service."""
        client = _make_client(settings, mem_service, raw_doc_service)
        client.get("/api/v1/knowledge/records?origin=agent&lifetime=session")

        _, call_kwargs = mem_service.list_records.await_args
        assert call_kwargs["lifetime"] == "session"

    def test_k3_lifetime_all_passed_to_service(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """K3 — ?lifetime=all&origin=all passes 'all' on agent leg, KB leg unaffected."""
        doc = _sample_raw_doc()
        raw_doc_service.list_records = AsyncMock(return_value=([doc], 1))
        client = _make_client(settings, mem_service, raw_doc_service)
        client.get("/api/v1/knowledge/records?origin=all&lifetime=all")

        _, call_kwargs = mem_service.list_records.await_args
        assert call_kwargs["lifetime"] == "all"

        # KB leg must NOT receive a lifetime kwarg — KB has no session concept.
        raw_doc_call = raw_doc_service.list_records.await_args
        assert raw_doc_call is not None
        assert "lifetime" not in raw_doc_call.kwargs, "KB leg must not receive lifetime kwarg"

    def test_k4_session_fields_populated_on_agent_row(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """K4 — session_id and ttl_expires_at are present in the response."""
        from datetime import UTC, datetime

        future_ttl = datetime(2099, 1, 1, tzinfo=UTC)
        record = _sample_mem_record(
            session_id="sess-abc",
            ttl_expires_at=future_ttl,
        )
        mem_service.list_records = AsyncMock(return_value=[record])
        mem_service.count_records = AsyncMock(return_value=1)
        raw_doc_service.list_records = AsyncMock(return_value=([], 0))
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=agent&lifetime=session")
        body = resp.json()
        assert resp.status_code == 200
        rec = body["records"][0]
        assert rec["session_id"] == "sess-abc"
        assert rec["ttl_expires_at"] is not None

    def test_k4_persistent_rows_have_null_session_fields(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """Persistent agent rows have session_id=None and ttl_expires_at=None."""
        record = _sample_mem_record()  # no session_id or ttl_expires_at
        mem_service.list_records = AsyncMock(return_value=[record])
        mem_service.count_records = AsyncMock(return_value=1)
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=agent")
        body = resp.json()
        rec = body["records"][0]
        assert rec["session_id"] is None
        assert rec["ttl_expires_at"] is None

    def test_k5_invalid_lifetime_is_422(self, client: TestClient) -> None:
        """K5 — ?lifetime=invalid returns 422."""
        resp = client.get("/api/v1/knowledge/records?lifetime=invalid")
        assert resp.status_code == 422

    def test_k6_kb_rows_always_have_null_session_fields(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """K6 — KB rows always return session_id=None and ttl_expires_at=None."""
        doc = _sample_raw_doc()
        raw_doc_service.list_records = AsyncMock(return_value=([doc], 1))
        mem_service.list_records = AsyncMock(return_value=[])
        mem_service.count_records = AsyncMock(return_value=0)
        client = _make_client(settings, mem_service, raw_doc_service)

        resp = client.get("/api/v1/knowledge/records?origin=kb&lifetime=session")
        body = resp.json()
        assert resp.status_code == 200
        for rec in body["records"]:
            assert rec["session_id"] is None
            assert rec["ttl_expires_at"] is None

    def test_k7_persistent_default_filters_out_session_rows(
        self,
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> None:
        """K7 — default lifetime=persistent: count_records is called with lifetime=persistent."""
        client = _make_client(settings, mem_service, raw_doc_service)
        client.get("/api/v1/knowledge/records?origin=agent")

        _, count_kwargs = mem_service.count_records.await_args
        assert count_kwargs["lifetime"] == "persistent"


# ---------------------------------------------------------------------------
# ?workspace_id query scoping + access check (Control Center, family B)
# ---------------------------------------------------------------------------


class TestWorkspaceQueryScoping:
    def _client(
        self,
        *,
        workspace_ids: list[str],
        settings: Settings,
        mem_service: MagicMock,
        raw_doc_service: AsyncMock,
    ) -> TestClient:
        app = FastAPI()
        app.state.settings = settings
        app.include_router(knowledge_router, prefix="/api/v1")
        app.dependency_overrides[get_memory_service] = lambda: mem_service
        app.dependency_overrides[get_raw_document_service] = lambda: raw_doc_service
        app.dependency_overrides[get_current_user] = lambda: _make_user()

        @app.middleware("http")
        async def _inject(request, call_next):  # type: ignore[no-untyped-def]
            request.state.user = {"workspace_ids": workspace_ids}
            return await call_next(request)

        return TestClient(app, raise_server_exceptions=False)

    def test_agent_leg_scopes_to_requested_workspace_for_star_token(
        self, settings: Settings, mem_service: MagicMock, raw_doc_service: AsyncMock
    ) -> None:
        client = self._client(
            workspace_ids=["*"],
            settings=settings,
            mem_service=mem_service,
            raw_doc_service=raw_doc_service,
        )

        resp = client.get("/api/v1/knowledge/records?origin=agent&workspace_id=ws-x")

        assert resp.status_code == 200
        assert mem_service.list_records.await_args.args[0] == "ws-x"

    def test_forbidden_for_non_member(
        self, settings: Settings, mem_service: MagicMock, raw_doc_service: AsyncMock
    ) -> None:
        client = self._client(
            workspace_ids=["ws-a"],
            settings=settings,
            mem_service=mem_service,
            raw_doc_service=raw_doc_service,
        )

        resp = client.get("/api/v1/knowledge/records?workspace_id=ws-x")

        assert resp.status_code == 403
        mem_service.list_records.assert_not_awaited()
