"""Integration test for ``metatron_memory_search`` status filter (MTRNIX-314).

Requires live PostgreSQL + Qdrant + Redis. Seeds two memory records (one
ACTIVE, one ARCHIVED) and verifies the default filter surfaces only the
ACTIVE one, while ``status=["all"]`` returns both.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from metatron.core.config import get_settings
from metatron.core.models import LifecycleStatus, MemoryRecord, MemoryScope
from metatron.mcp.tools import _memory_deps
from metatron.storage.memory_postgres import MemoryPostgresStore
from metatron.storage.memory_qdrant import MemoryQdrantStore

pytestmark = pytest.mark.integration


async def _cleanup(engine, workspace_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa_text("DELETE FROM memory_records WHERE workspace_id = :ws"),
            {"ws": workspace_id},
        )


async def test_search_default_filters_out_archived() -> None:
    settings = get_settings()
    workspace_id = f"search-it-{uuid4().hex[:8]}"

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_store = MemoryPostgresStore(engine)
    qdrant = MemoryQdrantStore(workspace_id=workspace_id)

    active_id = uuid4().hex
    archived_id = uuid4().hex
    try:
        active_rec = MemoryRecord(
            id=active_id,
            workspace_id=workspace_id,
            agent_id="agent-it",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="active unique phrase xyz123",
            content_hash=f"s-it-{active_id}",
            status=LifecycleStatus.ACTIVE,
        )
        archived_rec = MemoryRecord(
            id=archived_id,
            workspace_id=workspace_id,
            agent_id="agent-it",
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="archived unique phrase xyz123",
            content_hash=f"s-it-{archived_id}",
            status=LifecycleStatus.ARCHIVED,
        )
        await pg_store.save(active_rec)
        await pg_store.save(archived_rec)
        # Force archived status in PG (save() writes through server-defaults
        # and leaves status=active).
        await pg_store.update_lifecycle(workspace_id, archived_id, status=LifecycleStatus.ARCHIVED)
        # Upsert with the correct Qdrant status payload.
        await qdrant.upsert(active_rec)
        archived_rec.status = LifecycleStatus.ARCHIVED
        await qdrant.upsert(archived_rec)

        _memory_deps._reset_cache_for_tests()

        from metatron.mcp.tools.memory_search import metatron_memory_search

        # Default (no status) -> only ACTIVE.
        default_out = await metatron_memory_search(
            query="unique phrase xyz123",
            agent_id="agent-it",
            workspace_id=workspace_id,
            top_k=10,
        )
        assert "error" not in default_out
        ids = [r["record"]["id"] for r in default_out["results"]]
        assert active_id in ids
        assert archived_id not in ids

        # status=["all"] -> both.
        all_out = await metatron_memory_search(
            query="unique phrase xyz123",
            agent_id="agent-it",
            workspace_id=workspace_id,
            top_k=10,
            status=["all"],
        )
        assert "error" not in all_out
        ids_all = [r["record"]["id"] for r in all_out["results"]]
        assert active_id in ids_all
        # archived should be included.
        assert archived_id in ids_all
    finally:
        _memory_deps._reset_cache_for_tests()
        await qdrant.close()
        await _cleanup(engine, workspace_id)
        await engine.dispose()
