"""Tests for snapshot REST endpoints (MTRNIX-272).

Covers /api/v1/agents/{id}/reset, /api/v1/agents/{id}/snapshots POST + GET,
/api/v1/snapshots/{id}/restore, and /api/v1/snapshots/diff. Uses dependency
overrides so no real PG / Qdrant / FS access happens.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.agents.models import AgentRecord, AgentStatus
from metatron.agents.service import AgentNotFoundError, AgentRegistryService
from metatron.api.dependencies import (
    get_agent_registry_service,
    get_memory_service,
    get_memory_snapshot_service,
)
from metatron.api.routes.agents import router as agents_router
from metatron.api.routes.snapshots import router as snapshots_router
from metatron.auth.dependencies import get_current_user
from metatron.core.config import Settings
from metatron.core.exceptions import (
    MemoryNotFoundError,
    SnapshotCorruptError,
    SnapshotOverflowError,
)
from metatron.core.models import (
    LifecycleStatus,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySnapshot,
    Role,
    User,
)
from metatron.memory.service import MemoryService
from metatron.memory.snapshot import MemorySnapshotService, SnapshotDiff

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


def _sample_agent() -> AgentRecord:
    return AgentRecord(
        id="agent-1",
        workspace_id="ws-test",
        name="Trader",
        status=AgentStatus.STOPPED,
        model="gpt-4",
        config_version=1,
        current_config={
            "name": "Trader",
            "model": "gpt-4",
            "capabilities": [],
            "tools": [],
            "memory_bindings": {},
            "budget": {},
        },
        created_by="u1",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


def _sample_snapshot(
    snapshot_id: str = "snap-1",
    *,
    agent_id: str = "agent-1",
    trigger: str = "manual",
    record_count: int = 3,
) -> MemorySnapshot:
    return MemorySnapshot(
        id=snapshot_id,
        workspace_id="ws-test",
        agent_id=agent_id,
        label="snap label",
        trigger=trigger,
        record_count=record_count,
        content_hash="deadbeef",
        size_bytes=1024,
        storage_path=f"/tmp/{snapshot_id}.jsonl.gz",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


@pytest.fixture
def reg_service() -> AsyncMock:
    return AsyncMock(spec=AgentRegistryService)


@pytest.fixture
def mem_service() -> AsyncMock:
    return AsyncMock(spec=MemoryService)


@pytest.fixture
def snap_service() -> AsyncMock:
    return AsyncMock(spec=MemorySnapshotService)


@pytest.fixture
def make_client(
    settings: Settings,
    reg_service: AsyncMock,
    mem_service: AsyncMock,
    snap_service: AsyncMock,
) -> Callable[..., TestClient]:
    def _factory(role: Role = Role.EDITOR) -> TestClient:
        app = FastAPI()
        app.state.settings = settings
        app.include_router(agents_router, prefix="/api/v1")
        app.include_router(snapshots_router, prefix="/api/v1")
        app.dependency_overrides[get_agent_registry_service] = lambda: reg_service
        app.dependency_overrides[get_memory_service] = lambda: mem_service
        app.dependency_overrides[get_memory_snapshot_service] = lambda: snap_service
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
# POST /agents/{id}/reset
# ---------------------------------------------------------------------------


class TestResetAgent:
    def test_creates_pre_reset_snapshot_then_resets(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        mem_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.return_value = _sample_agent()
        snapshot = _sample_snapshot(trigger="pre_reset")
        snap_service.create.return_value = snapshot
        mem_service.reset.return_value = 7

        response = client.post("/api/v1/agents/agent-1/reset")

        assert response.status_code == 200
        body = response.json()
        assert body == {"snapshot_id": snapshot.id, "deleted_count": 7}
        snap_service.create.assert_awaited_once()
        mem_service.reset.assert_awaited_once()
        # Snapshot is created BEFORE reset so a snapshot failure never leaves
        # state wiped without backup.
        assert snap_service.create.await_args.args[0] == "agent-1"

    def test_404_when_agent_unknown(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        mem_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.side_effect = AgentNotFoundError("nope")

        response = client.post("/api/v1/agents/agent-x/reset")

        assert response.status_code == 404
        snap_service.create.assert_not_awaited()
        mem_service.reset.assert_not_awaited()

    def test_viewer_blocked(
        self,
        make_client: Callable[..., TestClient],
    ) -> None:
        client = make_client(Role.VIEWER)
        response = client.post("/api/v1/agents/agent-1/reset")
        assert response.status_code == 403

    def test_413_when_snapshot_overflows(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        mem_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.return_value = _sample_agent()
        snap_service.create.side_effect = SnapshotOverflowError(
            "snapshot would exceed 10000 records (found at least 10001 for agent 'agent-1')"
        )

        response = client.post("/api/v1/agents/agent-1/reset")

        assert response.status_code == 413
        assert "10000" in response.json()["detail"]
        # No reset happens when the snapshot fails.
        mem_service.reset.assert_not_awaited()

    def test_422_when_snapshot_corrupt(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        mem_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.return_value = _sample_agent()
        snap_service.create.side_effect = SnapshotCorruptError("file too big")

        response = client.post("/api/v1/agents/agent-1/reset")

        assert response.status_code == 422
        mem_service.reset.assert_not_awaited()

    def test_500_carries_snapshot_id_when_reset_fails(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        mem_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        # Pre-snapshot succeeds, then the wipe blows up. Operator must see
        # the snapshot id in the error so they can recover via /restore.
        reg_service.get_agent.return_value = _sample_agent()
        snapshot = _sample_snapshot(trigger="pre_reset")
        snap_service.create.return_value = snapshot
        mem_service.reset.side_effect = RuntimeError("PG connection lost")

        response = client.post("/api/v1/agents/agent-1/reset")

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail["snapshot_id"] == snapshot.id
        assert "PG connection lost" in detail["error"]
        assert "use the snapshot id" in detail["message"]


# ---------------------------------------------------------------------------
# POST /agents/{id}/snapshots
# ---------------------------------------------------------------------------


class TestCreateSnapshot:
    def test_201_returns_snapshot(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.return_value = _sample_agent()
        snap_service.create.return_value = _sample_snapshot()

        response = client.post(
            "/api/v1/agents/agent-1/snapshots",
            json={"label": "manual"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["id"] == "snap-1"
        assert body["agent_id"] == "agent-1"
        assert body["trigger"] == "manual"

    def test_404_when_agent_unknown(
        self,
        client: TestClient,
        reg_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.side_effect = AgentNotFoundError("nope")

        response = client.post(
            "/api/v1/agents/agent-x/snapshots",
            json={"label": "manual"},
        )

        assert response.status_code == 404

    def test_413_on_overflow(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.return_value = _sample_agent()
        snap_service.create.side_effect = SnapshotOverflowError("would exceed 10000 records")

        response = client.post(
            "/api/v1/agents/agent-1/snapshots",
            json={"label": "manual"},
        )
        assert response.status_code == 413

    def test_unrelated_runtime_error_still_500(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        # A bare RuntimeError (not SnapshotOverflowError) should NOT be
        # silently mapped to 413 — it must surface as 500. Guards against
        # the over-broad ``except RuntimeError`` flagged in PR review.
        reg_service.get_agent.return_value = _sample_agent()
        snap_service.create.side_effect = RuntimeError("disk full or other bug")

        response = client.post(
            "/api/v1/agents/agent-1/snapshots",
            json={"label": "manual"},
        )
        assert response.status_code == 500

    def test_422_on_corrupt(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.return_value = _sample_agent()
        snap_service.create.side_effect = SnapshotCorruptError("oversize")

        response = client.post(
            "/api/v1/agents/agent-1/snapshots",
            json={"label": "manual"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /agents/{id}/snapshots
# ---------------------------------------------------------------------------


class TestListSnapshots:
    def test_lists_newest_first(
        self,
        client: TestClient,
        reg_service: AsyncMock,
        snap_service: AsyncMock,
    ) -> None:
        reg_service.get_agent.return_value = _sample_agent()
        snap_service.list_snapshots.return_value = [
            _sample_snapshot("snap-2"),
            _sample_snapshot("snap-1"),
        ]

        response = client.get("/api/v1/agents/agent-1/snapshots")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert [s["id"] for s in body["snapshots"]] == ["snap-2", "snap-1"]


# ---------------------------------------------------------------------------
# POST /snapshots/{id}/restore
# ---------------------------------------------------------------------------


class TestRestoreSnapshot:
    def test_returns_pre_restore_and_count(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        pre_restore = _sample_snapshot("snap-pre", trigger="pre_restore")
        snap_service.restore.return_value = (pre_restore, 5)

        response = client.post("/api/v1/snapshots/snap-1/restore")

        assert response.status_code == 200
        body = response.json()
        assert body["snapshot_id"] == "snap-1"
        assert body["restored_count"] == 5
        assert body["pre_restore_snapshot"]["id"] == "snap-pre"

    def test_404_when_snapshot_missing(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.restore.side_effect = MemoryNotFoundError("no")
        response = client.post("/api/v1/snapshots/missing/restore")
        assert response.status_code == 404

    def test_422_when_corrupt(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.restore.side_effect = SnapshotCorruptError("bad checksum")
        response = client.post("/api/v1/snapshots/bad/restore")
        assert response.status_code == 422

    def test_413_when_pre_restore_snapshot_overflows(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        # restore() internally takes a pre_restore snapshot. If the agent's
        # current memory grew past the per-snapshot cap since the original
        # snapshot was taken, that internal create() raises
        # SnapshotOverflowError — must surface as 413 rather than 500.
        snap_service.restore.side_effect = SnapshotOverflowError(
            "snapshot would exceed 10000 records"
        )
        response = client.post("/api/v1/snapshots/snap-1/restore")
        assert response.status_code == 413
        assert "10000" in response.json()["detail"]

    def test_viewer_blocked(self, make_client: Callable[..., TestClient]) -> None:
        client = make_client(Role.VIEWER)
        response = client.post("/api/v1/snapshots/snap-1/restore")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /snapshots/diff
# ---------------------------------------------------------------------------


class TestDiff:
    def test_200_with_diff_payload(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.diff.return_value = SnapshotDiff(
            from_snapshot_id="a",
            to_snapshot_id="b",
            key="source",
            added=["r2"],
            removed=["r1"],
            changed=["r3"],
        )
        response = client.get("/api/v1/snapshots/diff?from=a&to=b")
        assert response.status_code == 200
        body = response.json()
        assert body["added"] == ["r2"]
        assert body["removed"] == ["r1"]
        assert body["changed"] == ["r3"]
        assert body["key"] == "source"

    def test_400_on_cross_agent(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.diff.side_effect = ValueError("same-agent only")
        response = client.get("/api/v1/snapshots/diff?from=a&to=b")
        assert response.status_code == 400

    def test_404_when_snapshot_missing(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.diff.side_effect = MemoryNotFoundError("no")
        response = client.get("/api/v1/snapshots/diff?from=a&to=b")
        assert response.status_code == 404

    def test_invalid_key_rejected_by_pydantic(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/v1/snapshots/diff?from=a&to=b&key=invalid")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /snapshots/{id}/records
# ---------------------------------------------------------------------------


def _memory_record(record_id: str = "r1") -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id="ws-test",
        agent_id="agent-1",
        scope=MemoryScope.PER_AGENT,
        kind=MemoryKind.FACT,
        source_type="conv",
        content=f"content of {record_id}",
        tags=["t1"],
        importance_score=0.5,
        content_hash=f"hash-{record_id}",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
        status=LifecycleStatus.ACTIVE,
    )


class TestReadSnapshotRecords:
    def test_returns_records_for_given_ids(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.read_records.return_value = [
            _memory_record("r1"),
            _memory_record("r3"),
        ]

        response = client.get("/api/v1/snapshots/snap-1/records?ids=r1&ids=r3")

        assert response.status_code == 200
        body = response.json()
        assert body["snapshot_id"] == "snap-1"
        assert body["count"] == 2
        assert [r["id"] for r in body["records"]] == ["r1", "r3"]
        # Service was called with the parsed id list and the snapshot id.
        snap_service.read_records.assert_awaited_once_with("snap-1", ids=["r1", "r3"])

    def test_422_when_ids_missing(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        # ids is required — there is no "give me everything" mode on the
        # HTTP surface. A consumer that wants the full snapshot must drive
        # it from a diff or list-records call and pass explicit ids.
        # FastAPI/Pydantic raises 422 for missing required query params.
        response = client.get("/api/v1/snapshots/snap-1/records")

        assert response.status_code == 422
        snap_service.read_records.assert_not_awaited()

    def test_rejects_too_many_ids(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        # Cap protects bandwidth + per-request payload size; an FE that needs
        # more must page through batches. Pydantic max_length validation kicks
        # in before the route body, so this is a 422 (validation error).
        many = "&".join(f"ids=r{i}" for i in range(201))
        response = client.get(f"/api/v1/snapshots/snap-1/records?{many}")

        assert response.status_code == 422
        snap_service.read_records.assert_not_awaited()

    def test_404_when_snapshot_missing(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.read_records.side_effect = MemoryNotFoundError("no")

        response = client.get("/api/v1/snapshots/missing/records?ids=r1")

        assert response.status_code == 404

    def test_422_when_corrupt(
        self,
        client: TestClient,
        snap_service: AsyncMock,
    ) -> None:
        snap_service.read_records.side_effect = SnapshotCorruptError("bad checksum")

        response = client.get("/api/v1/snapshots/bad/records?ids=r1")

        assert response.status_code == 422

    def test_viewer_allowed(
        self,
        make_client: Callable[..., TestClient],
        snap_service: AsyncMock,
    ) -> None:
        # Read-only — viewer can resolve snapshot record content for diff UI.
        snap_service.read_records.return_value = [_memory_record("r1")]
        viewer_client = make_client(Role.VIEWER)

        response = viewer_client.get("/api/v1/snapshots/snap-1/records?ids=r1")

        assert response.status_code == 200
