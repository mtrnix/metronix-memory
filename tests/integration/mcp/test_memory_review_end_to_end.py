"""End-to-end integration test for the memory review MCP tools (MTRNIX-314).

Requires: PostgreSQL (migration 018 applied), Qdrant, Redis. All services are
assumed running per CLAUDE.md.

Seeds a memory record + a ReviewEntry via FreshnessStore, then drives
``metronix_memory_review_list`` + ``metronix_memory_review_resolve`` (action
``keep``) to verify:
  * review_list returns the seeded entry
  * review_resolve transitions memory_records.status to ACTIVE
  * the review_entries row is deleted
  * a machine_events row with event_type=freshness_review_resolved is written
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import get_settings
from metronix.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    ReviewEntry,
)
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal
from metronix.mcp.tools import _agent_access, _memory_deps
from metronix.storage.freshness_pg import FreshnessStore
from metronix.storage.memory_postgres import MemoryPostgresStore

pytestmark = pytest.mark.integration


def _reset_mcp_caches() -> None:
    _memory_deps._reset_cache_for_tests()
    _agent_access.get_agent_access_authorizer.cache_clear()
    _agent_access.get_agent_access_audit_store.cache_clear()


async def _cleanup(engine, workspace_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa_text("DELETE FROM machine_events WHERE workspace_id = :ws"),
            {"ws": workspace_id},
        )
        await conn.execute(
            sa_text("DELETE FROM review_entries WHERE workspace_id = :ws"),
            {"ws": workspace_id},
        )
        await conn.execute(
            sa_text("DELETE FROM memory_records WHERE workspace_id = :ws"),
            {"ws": workspace_id},
        )
        await conn.execute(
            sa_text("DELETE FROM agent_access_grants WHERE workspace_id = :ws"),
            {"ws": workspace_id},
        )


async def test_memory_review_resolve_keep_end_to_end() -> None:
    settings = get_settings()
    workspace_id = f"review-it-{uuid4().hex[:8]}"
    agent_id = "agent-it"
    principal_user_id = f"review-user-{uuid4().hex[:8]}"
    record_id = uuid4().hex
    review_id = uuid4().hex

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_store = MemoryPostgresStore(engine)
    freshness_store = FreshnessStore(engine)
    principal_token = bind_principal(MCPPrincipal(principal_user_id, "editor", (workspace_id,)))

    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa_text("""
                    INSERT INTO agent_access_grants (
                        id, workspace_id, agent_id, principal_user_id, capability,
                        grant_type, granted_by_user_id
                    ) VALUES (
                        :id, :workspace_id, :agent_id, :principal_user_id, 'admin',
                        'owner', :principal_user_id
                    )
                """),
                {
                    "id": f"owner-{uuid4().hex}",
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "principal_user_id": principal_user_id,
                },
            )
        # --- Seed memory_records row with REVIEW_NEEDED status ---
        record = MemoryRecord(
            id=record_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            scope=MemoryScope.PER_AGENT,
            source_type="integration_test",
            content="review-it content snippet",
            content_hash=f"review-it-{record_id}",
        )
        await pg_store.save(record)
        # Force review_needed so we can verify transition.
        await pg_store.update_lifecycle(
            workspace_id,
            record_id,
            status=LifecycleStatus.REVIEW_NEEDED,
        )

        # --- Seed review_entries row directly via FreshnessStore ---
        entry = ReviewEntry(
            id=review_id,
            workspace_id=workspace_id,
            target_id=record_id,
            target_kind="memory_record",
            reason="possible_duplicate",
            related_record_id=None,
            content="dup preview",
            confidence=0.85,
        )
        await freshness_store.save_review_entry(entry)

        # --- Reset MCP service cache so our tool uses a fresh MemoryService
        # that picks up the same PG engine. ---
        _reset_mcp_caches()

        # --- Drive memory_review_list ---
        from metronix.mcp.tools.memory_review_list import (
            metronix_memory_review_list,
        )

        out = await metronix_memory_review_list(workspace_id=workspace_id, agent_id=agent_id)
        assert "error" not in out
        assert out["total"] >= 1
        seeded_ids = [e["id"] for e in out["entries"]]
        assert review_id in seeded_ids

        # --- Drive memory_review_resolve with action=keep ---
        from metronix.mcp.tools.memory_review_resolve import (
            metronix_memory_review_resolve,
        )

        resolve_out = await metronix_memory_review_resolve(
            review_id=review_id,
            action="keep",
            workspace_id=workspace_id,
            agent_id=agent_id,
            notes="integration test",
        )
        assert "error" not in resolve_out
        assert resolve_out["success"] is True
        assert resolve_out["new_status"] == "active"
        assert resolve_out["action"] == "keep"

        # --- Verify PG state ---
        rec = await pg_store.get(workspace_id, record_id)
        assert rec is not None
        assert rec.status == LifecycleStatus.ACTIVE
        assert rec.verification_state == "keep_resolved"

        # Review entry gone.
        remaining = await freshness_store.list_review_entries(
            workspace_id, target_kind="memory_record"
        )
        assert all(e.id != review_id for e in remaining)

        # MachineEvent written.
        events = await freshness_store.list_events_for_target(
            workspace_id, "memory_record", record_id
        )
        assert any(
            e.event_type == "freshness_review_resolved" and e.actor == "mcp:agent-access-v1"
            for e in events
        )
    finally:
        reset_principal(principal_token)
        _reset_mcp_caches()
        await _cleanup(engine, workspace_id)
        await engine.dispose()
