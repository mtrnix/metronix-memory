"""Integration tests for BootstrapStateStore against live PostgreSQL (MTRNIX-352, T2).

Requires dev stack running (``make docker-up``) and migration 023 applied.
Marked ``integration`` — runs only under ``make test-all``.

Each test cleans up its own rows after completion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.storage.bootstrap_state import BootstrapStateStore
from metatron.workspaces.bootstrap.models import BootstrapStateEnum

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    settings = get_settings()
    e = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    yield e
    await e.dispose()


@pytest.fixture
async def store(engine):
    return BootstrapStateStore(engine)


def _ws(suffix: str = "") -> str:
    return f"test-bs-{uuid4().hex[:8]}{suffix}"


async def _cleanup(engine, workspace_id: str) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM bootstrap_state WHERE workspace_id = :w"),
            {"w": workspace_id},
        )


# ---------------------------------------------------------------------------
# Basic CRUD round-trip
# ---------------------------------------------------------------------------


class TestBootstrapStateStorePg:
    async def test_upsert_initial_and_get(self, store, engine) -> None:
        wid = _ws()
        try:
            created = await store.upsert_initial(wid, total_count=100)
            assert created.workspace_id == wid
            assert created.state == BootstrapStateEnum.BOOTSTRAPPING
            assert created.total_count == 100

            fetched = await store.get(wid)
            assert fetched is not None
            assert fetched.workspace_id == wid
            assert fetched.state == BootstrapStateEnum.BOOTSTRAPPING
        finally:
            await _cleanup(engine, wid)

    async def test_upsert_is_idempotent_on_conflict(self, store, engine) -> None:
        wid = _ws()
        try:
            first = await store.upsert_initial(wid)
            second = await store.upsert_initial(wid)
            assert first.workspace_id == second.workspace_id
        finally:
            await _cleanup(engine, wid)

    async def test_set_state(self, store, engine) -> None:
        wid = _ws()
        try:
            await store.upsert_initial(wid)
            await store.set_state(wid, state=BootstrapStateEnum.READY)
            state = await store.get(wid)
            assert state is not None
            assert state.state == BootstrapStateEnum.READY
        finally:
            await _cleanup(engine, wid)

    async def test_set_failed_and_list_ready_for_retry(self, store, engine) -> None:
        wid = _ws()
        try:
            await store.upsert_initial(wid)
            next_retry = datetime.now(UTC) - timedelta(seconds=10)  # already due
            await store.set_failed(
                wid, last_error="boom", next_retry_at=next_retry, increment_retry=True
            )

            candidates = await store.list_failed_ready_for_retry(
                now=datetime.now(UTC), max_attempts=5
            )
            wids = [c.workspace_id for c in candidates]
            assert wid in wids
        finally:
            await _cleanup(engine, wid)

    async def test_cas_set_state_succeeds_on_match(self, store, engine) -> None:
        wid = _ws()
        try:
            await store.upsert_initial(wid)
            next_retry = datetime.now(UTC) - timedelta(seconds=5)
            await store.set_failed(
                wid, last_error="x", next_retry_at=next_retry, increment_retry=True
            )

            won = await store.cas_set_state(
                wid,
                from_state=BootstrapStateEnum.FAILED,
                to_state=BootstrapStateEnum.BOOTSTRAPPING,
            )
            assert won is True
            state = await store.get(wid)
            assert state is not None
            assert state.state == BootstrapStateEnum.BOOTSTRAPPING
        finally:
            await _cleanup(engine, wid)

    async def test_cas_set_state_fails_on_mismatch(self, store, engine) -> None:
        wid = _ws()
        try:
            await store.upsert_initial(wid)  # state = bootstrapping
            won = await store.cas_set_state(
                wid,
                from_state=BootstrapStateEnum.FAILED,  # wrong from
                to_state=BootstrapStateEnum.READY,
            )
            assert won is False
        finally:
            await _cleanup(engine, wid)

    async def test_delete_returns_true(self, store, engine) -> None:
        wid = _ws()
        await store.upsert_initial(wid)
        result = await store.delete(wid)
        assert result is True
        assert await store.get(wid) is None

    async def test_delete_absent_returns_false(self, store, engine) -> None:
        result = await store.delete("ws-nonexistent-xyz")
        assert result is False

    async def test_update_checkpoint(self, store, engine) -> None:
        wid = _ws()
        try:
            await store.upsert_initial(wid)
            await store.update_checkpoint(
                wid,
                current_step="ingesting",
                indexed_count=50,
                progress=0.5,
            )
            state = await store.get(wid)
            assert state is not None
            assert state.current_step == "ingesting"
            assert state.indexed_count == 50
            assert abs(state.progress - 0.5) < 0.001
        finally:
            await _cleanup(engine, wid)

    async def test_find_stale_bootstrapping(self, store, engine) -> None:
        wid = _ws()
        try:
            await store.upsert_initial(wid)
            # Updated_at is NOW(), so threshold in the past should NOT catch it
            future_threshold = datetime.now(UTC) - timedelta(hours=1)
            stale = await store.find_stale_bootstrapping(stale_threshold=future_threshold)
            assert wid not in stale

            # Threshold in the future should catch it
            past_threshold = datetime.now(UTC) + timedelta(minutes=1)
            stale2 = await store.find_stale_bootstrapping(stale_threshold=past_threshold)
            assert wid in stale2
        finally:
            await _cleanup(engine, wid)

    async def test_reset_retry(self, store, engine) -> None:
        wid = _ws()
        try:
            await store.upsert_initial(wid)
            next_retry = datetime.now(UTC) + timedelta(minutes=5)
            await store.set_failed(
                wid, last_error="err", next_retry_at=next_retry, increment_retry=True
            )
            await store.reset_retry(wid)
            state = await store.get(wid)
            assert state is not None
            assert state.retry_count == 0
            assert state.next_retry_at is None
            assert state.last_error is None
        finally:
            await _cleanup(engine, wid)
