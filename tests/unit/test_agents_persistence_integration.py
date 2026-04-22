"""Integration tests for :class:`AgentPersistence` against a live PostgreSQL.

Skipped by default (``make test``); run explicitly via ``make test-all`` or
``pytest -m integration``. These tests exercise paths that mocks cannot —
real ``IntegrityError`` mapping, ``SELECT … FOR UPDATE`` semantics under
concurrent transactions, and the partial unique index on ``agents``.

The fixture resolves the DSN from ``Settings`` (same env vars as production:
``POSTGRES_HOST``, ``POSTGRES_PORT`` …) and assumes ``alembic upgrade head``
has been applied. Each test isolates its state by using a per-test
``workspace_id`` seeded with ``uuid4``, then cleans up at teardown.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from metatron.agents.models import AgentRecord, AgentStatus
from metatron.agents.persistence import AgentPersistence, _AgentNameConflictError
from metatron.core.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Async engine bound to the real project PostgreSQL."""
    settings = Settings()
    eng = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def repo(engine: AsyncEngine) -> AgentPersistence:
    return AgentPersistence(engine)


@pytest.fixture
async def workspace_id(engine: AsyncEngine) -> AsyncIterator[str]:
    """Per-test workspace with guaranteed cleanup. agent_config_versions is
    wiped by the ``ON DELETE CASCADE`` FK when the agent row is removed."""
    ws = f"ws-it-{uuid4().hex[:12]}"
    yield ws
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM agents WHERE workspace_id = :ws"), {"ws": ws})


def _record(workspace_id: str, **overrides: Any) -> AgentRecord:
    base = AgentRecord(
        workspace_id=workspace_id,
        name=overrides.pop("name", f"agent-{uuid4().hex[:6]}"),
        status=overrides.pop("status", AgentStatus.STOPPED),
        model="gpt-4",
        capabilities=["trade"],
        tools=["search"],
        memory_bindings={"scopes": ["PER_AGENT"]},
        budget={"tokens_per_day": 10000},
        config_version=1,
        current_config={"name": "x"},
        created_by="u1",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


# ---------------------------------------------------------------------------
# Happy-path CRUD round-trip
# ---------------------------------------------------------------------------


class TestSaveNewAndGet:
    async def test_persists_agent_and_seeds_version_row(
        self,
        repo: AgentPersistence,
        engine: AsyncEngine,
        workspace_id: str,
    ) -> None:
        rec = _record(workspace_id, name="trader-a", model="claude-sonnet-4-6")
        saved = await repo.save_new(rec)

        # Read back through the repo.
        fetched = await repo.get(workspace_id, saved.id)
        assert fetched is not None
        assert fetched.id == saved.id
        assert fetched.name == "trader-a"
        assert fetched.model == "claude-sonnet-4-6"
        assert fetched.status is AgentStatus.STOPPED
        assert fetched.config_version == 1

        # Version row must exist with version=1.
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT version, changed_by FROM agent_config_versions WHERE agent_id = :id"),
                {"id": saved.id},
            )
            rows = result.fetchall()
        assert len(rows) == 1
        assert rows[0]._mapping["version"] == 1
        assert rows[0]._mapping["changed_by"] == "u1"


# ---------------------------------------------------------------------------
# Unique-name enforcement — IntegrityError mapping and partial index
# ---------------------------------------------------------------------------


class TestUniqueName:
    async def test_duplicate_name_raises_conflict(
        self, repo: AgentPersistence, workspace_id: str
    ) -> None:
        await repo.save_new(_record(workspace_id, name="dup"))
        with pytest.raises(_AgentNameConflictError):
            await repo.save_new(_record(workspace_id, name="dup"))

    async def test_name_reuse_after_archive_succeeds(
        self, repo: AgentPersistence, workspace_id: str
    ) -> None:
        """Partial index `WHERE status <> 'archived'` frees the name slot
        after soft-delete — a fresh registration with the same name must
        succeed without a 409."""
        first = await repo.save_new(_record(workspace_id, name="reusable"))
        await repo.update_status(workspace_id, first.id, AgentStatus.ARCHIVED)

        second = await repo.save_new(_record(workspace_id, name="reusable"))
        assert second.id != first.id
        assert second.status is AgentStatus.STOPPED

    async def test_same_name_different_workspaces_allowed(
        self,
        repo: AgentPersistence,
        engine: AsyncEngine,
        workspace_id: str,
    ) -> None:
        other_ws = f"ws-it-{uuid4().hex[:12]}"
        await repo.save_new(_record(workspace_id, name="shared"))
        try:
            await repo.save_new(_record(other_ws, name="shared"))
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM agents WHERE workspace_id = :ws"),
                    {"ws": other_ws},
                )


# ---------------------------------------------------------------------------
# Default list excludes archived (BLOCKER #1)
# ---------------------------------------------------------------------------


class TestArchivedVisibility:
    async def test_default_list_excludes_archived(
        self, repo: AgentPersistence, workspace_id: str
    ) -> None:
        alive = await repo.save_new(_record(workspace_id, name="alive"))
        doomed = await repo.save_new(_record(workspace_id, name="doomed"))
        await repo.update_status(workspace_id, doomed.id, AgentStatus.ARCHIVED)

        listed = await repo.list_records(workspace_id)
        ids = {r.id for r in listed}
        assert alive.id in ids
        assert doomed.id not in ids

    async def test_explicit_archived_status_returns_them(
        self, repo: AgentPersistence, workspace_id: str
    ) -> None:
        archived = await repo.save_new(_record(workspace_id, name="gone"))
        await repo.update_status(workspace_id, archived.id, AgentStatus.ARCHIVED)

        listed = await repo.list_records(workspace_id, status=AgentStatus.ARCHIVED)
        assert [r.id for r in listed] == [archived.id]

    async def test_other_status_filter_does_not_leak_archived(
        self, repo: AgentPersistence, workspace_id: str
    ) -> None:
        stopped = await repo.save_new(_record(workspace_id, name="stopped-one"))
        gone = await repo.save_new(_record(workspace_id, name="gone-one"))
        await repo.update_status(workspace_id, gone.id, AgentStatus.ARCHIVED)

        listed = await repo.list_records(workspace_id, status=AgentStatus.STOPPED)
        assert [r.id for r in listed] == [stopped.id]


# ---------------------------------------------------------------------------
# update_with_version_bump — transaction, version bump, history
# ---------------------------------------------------------------------------


class TestUpdateWithVersionBump:
    async def test_bumps_version_and_appends_history(
        self,
        repo: AgentPersistence,
        engine: AsyncEngine,
        workspace_id: str,
    ) -> None:
        original = await repo.save_new(_record(workspace_id, name="vroom", model="gpt-4"))

        new_snapshot = {
            "name": "vroom",
            "model": "claude-opus-4-7",
            "capabilities": ["trade", "analyze"],
            "tools": ["search"],
            "memory_bindings": {"scopes": ["PER_AGENT"]},
            "budget": {"tokens_per_day": 10000},
        }
        updated = await repo.update_with_version_bump(
            workspace_id,
            original.id,
            new_fields={**new_snapshot, "current_config": new_snapshot},
            changed_by="u2",
        )
        assert updated is not None
        assert updated.config_version == 2
        assert updated.model == "claude-opus-4-7"
        assert updated.capabilities == ["trade", "analyze"]

        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT version, changed_by, config FROM agent_config_versions "
                        "WHERE agent_id = :id ORDER BY version"
                    ),
                    {"id": original.id},
                )
            ).fetchall()
        assert [r._mapping["version"] for r in rows] == [1, 2]
        assert rows[1]._mapping["changed_by"] == "u2"
        assert rows[1]._mapping["config"]["model"] == "claude-opus-4-7"

    async def test_missing_agent_returns_none(
        self, repo: AgentPersistence, workspace_id: str
    ) -> None:
        result = await repo.update_with_version_bump(
            workspace_id,
            "does-not-exist",
            new_fields={"name": "x", "current_config": {"name": "x"}},
            changed_by="u1",
        )
        assert result is None

    async def test_rename_into_existing_name_raises_conflict(
        self, repo: AgentPersistence, workspace_id: str
    ) -> None:
        await repo.save_new(_record(workspace_id, name="taken"))
        other = await repo.save_new(_record(workspace_id, name="free"))

        with pytest.raises(_AgentNameConflictError):
            await repo.update_with_version_bump(
                workspace_id,
                other.id,
                new_fields={"name": "taken", "current_config": {"name": "taken"}},
                changed_by="u1",
            )

    async def test_select_for_update_serializes_concurrent_updates(
        self,
        engine: AsyncEngine,
        workspace_id: str,
    ) -> None:
        """Two parallel updates on the same agent must serialize — both
        complete with monotonically increasing versions and both history
        rows end up persisted. Without ``SELECT … FOR UPDATE`` in
        ``update_with_version_bump`` the second caller could overwrite the
        first (lost update)."""
        # Each coroutine uses its own repo bound to the shared engine so the
        # pool gives them independent connections.
        repo_a = AgentPersistence(engine)
        repo_b = AgentPersistence(engine)

        seed = await repo_a.save_new(_record(workspace_id, name="racer"))

        async def bump(repo: AgentPersistence, model: str) -> int | None:
            result = await repo.update_with_version_bump(
                workspace_id,
                seed.id,
                new_fields={
                    "name": "racer",
                    "model": model,
                    "capabilities": ["trade"],
                    "tools": ["search"],
                    "memory_bindings": {"scopes": ["PER_AGENT"]},
                    "budget": {"tokens_per_day": 10000},
                    "current_config": {"model": model},
                },
                changed_by=f"u-{model}",
            )
            return None if result is None else result.config_version

        versions = await asyncio.gather(
            bump(repo_a, "claude-opus-4-7"),
            bump(repo_b, "claude-sonnet-4-6"),
        )
        assert sorted(versions) == [2, 3]

        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT version FROM agent_config_versions "
                        "WHERE agent_id = :id ORDER BY version"
                    ),
                    {"id": seed.id},
                )
            ).fetchall()
        assert [r._mapping["version"] for r in rows] == [1, 2, 3]


# ---------------------------------------------------------------------------
# list_versions JOIN — workspace isolation enforced at the DB
# ---------------------------------------------------------------------------


class TestListVersionsJoinIsolation:
    async def test_other_workspace_cannot_see_versions(
        self,
        repo: AgentPersistence,
        engine: AsyncEngine,
        workspace_id: str,
    ) -> None:
        """list_versions JOINs agents to enforce workspace_id match at the
        DB. Even if a caller guesses the agent_id, a different workspace
        must get an empty list rather than version history."""
        seed = await repo.save_new(_record(workspace_id, name="secret"))

        other_ws = f"ws-it-{uuid4().hex[:12]}"
        try:
            # Same agent_id, wrong workspace → empty list (JOIN filters out).
            versions = await repo.list_versions(other_ws, seed.id)
            assert versions == []

            # Own workspace → sees v1.
            own_versions = await repo.list_versions(workspace_id, seed.id)
            assert [v.version for v in own_versions] == [1]
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM agents WHERE workspace_id = :ws"),
                    {"ws": other_ws},
                )
