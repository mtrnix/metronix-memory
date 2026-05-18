"""Unit tests for BootstrapStateStore DAO (MTRNIX-352, T2).

Uses mock async engine — no live DB.  Verifies SQL text, parameter bindings,
and row-to-dataclass mapping.  Pattern mirrors test_chat_persistence.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from metatron.workspaces.bootstrap.store import BootstrapStateStore
from metatron.workspaces.bootstrap.models import BootstrapStateEnum

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_row(data: dict[str, Any]) -> MagicMock:
    mapping = MagicMock()
    mapping.__getitem__ = lambda self, k: data[k]
    mapping.get = lambda k, default=None: data.get(k, default)
    row = MagicMock()
    row._mapping = mapping
    return row


class _FakeCtx:
    def __init__(self, conn: AsyncMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> AsyncMock:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        pass


def _make_store_and_conn(row_data: dict | None = None) -> tuple[BootstrapStateStore, AsyncMock]:
    engine = MagicMock()
    conn = AsyncMock()
    result = MagicMock()
    if row_data is not None:
        row = _make_row(row_data)
        result.first.return_value = row
        result.fetchall.return_value = [row]
    else:
        result.first.return_value = None
        result.fetchall.return_value = []
    conn.execute.return_value = result
    engine.connect.return_value = _FakeCtx(conn)
    engine.begin.return_value = _FakeCtx(conn)
    return BootstrapStateStore(engine), conn


_NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)

_SAMPLE_ROW: dict[str, Any] = {
    "workspace_id": "ws-1",
    "state": "bootstrapping",
    "progress": 0.0,
    "current_step": None,
    "last_processed_resource": None,
    "last_processed_id": None,
    "indexed_count": 0,
    "total_count": None,
    "last_error": None,
    "last_synced_at": None,
    "retry_count": 0,
    "next_retry_at": None,
    "updated_at": _NOW,
}


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_state_on_hit(self) -> None:
        store, conn = _make_store_and_conn(_SAMPLE_ROW)
        result = await store.get("ws-1")

        assert result is not None
        assert result.workspace_id == "ws-1"
        assert result.state == BootstrapStateEnum.BOOTSTRAPPING
        conn.execute.assert_called_once()
        sql_text = str(conn.execute.call_args.args[0])
        assert "bootstrap_state" in sql_text

    async def test_returns_none_on_miss(self) -> None:
        store, conn = _make_store_and_conn(None)
        result = await store.get("ws-missing")
        assert result is None


# ---------------------------------------------------------------------------
# upsert_initial()
# ---------------------------------------------------------------------------


class TestUpsertInitial:
    async def test_upsert_returns_bootstrapping_state(self) -> None:
        store, conn = _make_store_and_conn(_SAMPLE_ROW)
        result = await store.upsert_initial("ws-1")

        assert result.state == BootstrapStateEnum.BOOTSTRAPPING
        assert result.workspace_id == "ws-1"
        sql_text = str(conn.execute.call_args.args[0])
        assert "ON CONFLICT" in sql_text

    async def test_total_count_passed_as_parameter(self) -> None:
        store, conn = _make_store_and_conn(_SAMPLE_ROW)
        await store.upsert_initial("ws-1", total_count=42)
        params = conn.execute.call_args.args[1]
        assert params["t"] == 42


# ---------------------------------------------------------------------------
# cas_set_state()
# ---------------------------------------------------------------------------


class TestCasSetState:
    async def test_returns_true_on_success(self) -> None:
        store, conn = _make_store_and_conn(_SAMPLE_ROW)
        won = await store.cas_set_state(
            "ws-1",
            from_state=BootstrapStateEnum.FAILED,
            to_state=BootstrapStateEnum.BOOTSTRAPPING,
        )
        assert won is True

    async def test_returns_false_on_miss(self) -> None:
        store, conn = _make_store_and_conn(None)
        won = await store.cas_set_state(
            "ws-1",
            from_state=BootstrapStateEnum.FAILED,
            to_state=BootstrapStateEnum.BOOTSTRAPPING,
        )
        assert won is False


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_returns_true_when_row_deleted(self) -> None:
        store, conn = _make_store_and_conn(_SAMPLE_ROW)
        result = await store.delete("ws-1")
        assert result is True

    async def test_returns_false_when_row_absent(self) -> None:
        store, conn = _make_store_and_conn(None)
        result = await store.delete("ws-missing")
        assert result is False


# ---------------------------------------------------------------------------
# list_failed_ready_for_retry()
# ---------------------------------------------------------------------------


class TestListFailedReadyForRetry:
    async def test_returns_list_of_states(self) -> None:
        failed_row = {**_SAMPLE_ROW, "state": "failed", "retry_count": 1}
        store, conn = _make_store_and_conn(failed_row)
        results = await store.list_failed_ready_for_retry(now=_NOW, max_attempts=5)

        assert len(results) == 1
        assert results[0].state == BootstrapStateEnum.FAILED

    async def test_passes_correct_params(self) -> None:
        store, conn = _make_store_and_conn(None)
        await store.list_failed_ready_for_retry(now=_NOW, max_attempts=3, limit=10)
        params = conn.execute.call_args.args[1]
        assert params["max"] == 3
        assert params["limit"] == 10
        assert params["now"] == _NOW


# ---------------------------------------------------------------------------
# find_stale_bootstrapping()
# ---------------------------------------------------------------------------


class TestFindStaleBootstrapping:
    async def test_returns_workspace_ids(self) -> None:
        row_data = {"workspace_id": "ws-stale"}
        store, conn = _make_store_and_conn(row_data)
        results = await store.find_stale_bootstrapping(stale_threshold=_NOW)

        assert results == ["ws-stale"]
