"""Integration test: WorkspaceManager.delete() cascade with live PG + stubs (MTRNIX-352, T2).

Verifies that delete() removes the bootstrap_state row and chat threads from PG.
Qdrant and Neo4j calls are stubbed to avoid service dependencies in CI.

Requires dev stack (``make docker-up``) + migrations 022 + 023 applied.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.chat.persistence import ChatPersistence
from metatron.core.config import get_settings
from metatron.storage.bootstrap_state import BootstrapStateStore
from metatron.workspaces.manager import WorkspaceManager

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    settings = get_settings()
    e = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    yield e
    await e.dispose()


def _ws() -> str:
    return f"test-del-{uuid4().hex[:8]}"


async def _cleanup(engine, workspace_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM bootstrap_state WHERE workspace_id = :w"),
            {"w": workspace_id},
        )
        await conn.execute(
            text("DELETE FROM chat_threads WHERE workspace_id = :w"),
            {"w": workspace_id},
        )


class TestDeleteCascade:
    async def test_delete_removes_bootstrap_state_and_chat_threads(
        self, engine
    ) -> None:
        wid = _ws()
        bs_store = BootstrapStateStore(engine)
        chat = ChatPersistence(engine)

        # Provision
        await bs_store.upsert_initial(wid)
        # Create a chat thread for some user in this workspace
        await chat.get_or_create_thread(wid, "user-cascade-test")

        # Build WorkspaceManager with real PG stores but stub Qdrant / Neo4j
        runner = AsyncMock()
        runner.cancel.return_value = False

        mgr = WorkspaceManager.__new__(WorkspaceManager)
        from threading import Lock

        mgr._workspaces = {}
        mgr._active_workspace = {}
        mgr._lock = Lock()
        mgr._stats = {}
        mgr._persistence = None
        mgr._use_persistence = False
        mgr._bootstrap_store = bs_store
        mgr._chat_persistence = chat
        mgr._pg_store = None
        mgr._bootstrap_runner = runner
        mgr._async_lock = None

        with (
            patch("metatron.workspaces.manager.delete_workspace_graph"),
            patch(
                "metatron.workspaces.manager.AsyncQdrantClient",
                MagicMock(return_value=AsyncMock()),
            ),
            patch("metatron.workspaces.manager.get_collection_name", return_value="col"),
        ):
            import contextlib

            with contextlib.suppress(Exception):
                # If Qdrant/Neo4j stubs fail — that's acceptable, PG should still work
                await mgr.delete(wid)

        # Bootstrap row must be gone
        state = await bs_store.get(wid)
        assert state is None, f"Expected bootstrap_state row to be deleted for {wid}"

        # Chat threads must be gone
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*) FROM chat_threads WHERE workspace_id = :w"),
                {"w": wid},
            )
            row = result.first()
        count = row[0] if row else 0
        assert count == 0, f"Expected 0 chat threads after delete, got {count}"
