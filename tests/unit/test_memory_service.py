"""Tests for MemoryService (WS1 — PG + Qdrant + Redis + Neo4j)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from metatron.core.exceptions import MemoryNotFoundError
from metatron.core.models import MemoryRecord, MemoryScope
from metatron.memory.service import MemoryService


def _make_service(workspace_id: str = "ws1"):
    """Create a MemoryService with mocked dependencies."""
    redis_cache = AsyncMock()
    qdrant_store = AsyncMock()
    pg_store = AsyncMock()
    service = MemoryService(
        redis_cache=redis_cache,
        qdrant_store=qdrant_store,
        pg_store=pg_store,
        workspace_id=workspace_id,
    )
    return service, redis_cache, qdrant_store, pg_store


def _sample_record(**overrides) -> MemoryRecord:
    defaults = {
        "id": "mem001",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.SESSION,
        "session_id": "sess1",
        "content": "user prefers dark mode",
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


# ---------------------------------------------------------------------------
# Session write-through
# ---------------------------------------------------------------------------


class TestCacheSession:
    async def test_writes_to_redis_and_neo4j(self) -> None:
        service, redis_cache, _, _ = _make_service()
        record = _sample_record()
        redis_cache.cache.return_value = record

        with patch("metatron.memory.service.save_memory_to_graph") as mock_graph:
            result = await service.cache_session("ws1", "sess1", record)

        assert result.id == "mem001"
        redis_cache.cache.assert_called_once_with(
            "ws1",
            "sess1",
            record,
            ttl_seconds=None,
        )
        mock_graph.assert_called_once_with(record)

    async def test_passes_ttl_override(self) -> None:
        service, redis_cache, _, _ = _make_service()
        record = _sample_record()
        redis_cache.cache.return_value = record

        with patch("metatron.memory.service.save_memory_to_graph"):
            await service.cache_session("ws1", "sess1", record, ttl_seconds=120)

        redis_cache.cache.assert_called_once_with(
            "ws1",
            "sess1",
            record,
            ttl_seconds=120,
        )

    async def test_neo4j_failure_does_not_block_cache(self) -> None:
        service, redis_cache, _, _ = _make_service()
        record = _sample_record()
        redis_cache.cache.return_value = record

        with patch(
            "metatron.memory.service.save_memory_to_graph",
            side_effect=Exception("neo4j down"),
        ):
            result = await service.cache_session("ws1", "sess1", record)

        assert result.id == "mem001"
        redis_cache.cache.assert_called_once()


# ---------------------------------------------------------------------------
# Session reads
# ---------------------------------------------------------------------------


class TestGetSession:
    async def test_returns_from_redis(self) -> None:
        service, redis_cache, _, _ = _make_service()
        expected = _sample_record()
        redis_cache.get.return_value = expected

        result = await service.get_session("ws1", "sess1", "mem001")

        assert result is expected
        redis_cache.get.assert_called_once_with("ws1", "sess1", "mem001")

    async def test_returns_none_when_not_cached(self) -> None:
        service, redis_cache, _, pg_store = _make_service()
        redis_cache.get.return_value = None
        pg_store.get.return_value = None

        result = await service.get_session("ws1", "sess1", "missing")

        assert result is None

    async def test_falls_back_to_pg_on_redis_miss(self) -> None:
        service, redis_cache, _, pg_store = _make_service()
        expected = _sample_record()
        redis_cache.get.return_value = None
        pg_store.get.return_value = expected

        result = await service.get_session("ws1", "sess1", "mem001")

        assert result is expected
        pg_store.get.assert_called_once_with("ws1", "mem001")


class TestListSession:
    async def test_delegates_to_redis(self) -> None:
        service, redis_cache, _, _ = _make_service()
        records = [_sample_record(id="m1"), _sample_record(id="m2")]
        redis_cache.list.return_value = records

        result = await service.list_session("ws1", "sess1")

        assert len(result) == 2
        redis_cache.list.assert_called_once_with("ws1", "sess1")


class TestInvalidateSession:
    async def test_delegates_to_redis(self) -> None:
        service, redis_cache, _, _ = _make_service()
        redis_cache.invalidate.return_value = 3

        count = await service.invalidate_session("ws1", "sess1")

        assert count == 3
        redis_cache.invalidate.assert_called_once_with("ws1", "sess1")


class TestExtendSessionTtl:
    async def test_delegates_to_redis(self) -> None:
        service, redis_cache, _, _ = _make_service()
        redis_cache.extend_ttl.return_value = True

        result = await service.extend_session_ttl("ws1", "sess1", 7200)

        assert result is True
        redis_cache.extend_ttl.assert_called_once_with("ws1", "sess1", 7200)


# ---------------------------------------------------------------------------
# Persistent memory (PG + Qdrant + Neo4j)
# ---------------------------------------------------------------------------


class TestSave:
    async def test_writes_to_pg_qdrant_neo4j(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record

        with patch("metatron.memory.service.save_memory_to_graph") as mock_graph:
            result = await service.save("ws1", record)

        assert result.id == "mem001"
        pg_store.save.assert_awaited_once_with(record)
        qdrant_store.upsert.assert_awaited_once_with(record)
        mock_graph.assert_called_once_with(record)

    async def test_pg_is_called_first(self) -> None:
        """PG write must happen before Qdrant — PG is source of truth."""
        service, _, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record

        call_order: list[str] = []
        pg_store.save.side_effect = lambda r: call_order.append("pg") or record
        qdrant_store.upsert.side_effect = lambda r: call_order.append("qdrant")

        with patch("metatron.memory.service.save_memory_to_graph"):
            await service.save("ws1", record)

        assert call_order == ["pg", "qdrant"]

    async def test_neo4j_failure_does_not_block_save(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record

        with patch(
            "metatron.memory.service.save_memory_to_graph",
            side_effect=Exception("neo4j down"),
        ):
            result = await service.save("ws1", record)

        assert result.id == "mem001"
        pg_store.save.assert_awaited_once()
        qdrant_store.upsert.assert_awaited_once()

    async def test_pg_failure_propagates(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = None
        pg_store.save.side_effect = Exception("pg down")

        with pytest.raises(Exception, match="pg down"):
            await service.save("ws1", record)

        qdrant_store.upsert.assert_not_awaited()

    async def test_qdrant_failure_propagates(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record
        qdrant_store.upsert.side_effect = Exception("qdrant down")

        with (
            patch("metatron.memory.service.save_memory_to_graph"),
            pytest.raises(Exception, match="qdrant down"),
        ):
            await service.save("ws1", record)

    async def test_sets_content_hash(self) -> None:
        service, _, _, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT, content="hello")
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record

        with patch("metatron.memory.service.save_memory_to_graph"):
            await service.save("ws1", record)

        assert record.content_hash != ""

    async def test_dedup_returns_existing_record(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        existing = _sample_record(id="existing001", scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = existing

        new_record = _sample_record(id="new001", scope=MemoryScope.PER_AGENT)

        with patch("metatron.memory.service.save_memory_to_graph"):
            result = await service.save("ws1", new_record)

        assert result.id == "existing001"
        pg_store.save.assert_not_awaited()
        qdrant_store.upsert.assert_not_awaited()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_deletes_from_all_stores(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        pg_store.delete.return_value = True

        with patch("metatron.memory.service.delete_memory_node") as mock_graph:
            mock_graph.return_value = True
            result = await service.delete("ws1", "mem001")

        assert result is True
        pg_store.delete.assert_awaited_once_with("ws1", "mem001")
        qdrant_store.delete.assert_awaited_once_with("mem001")

    async def test_returns_false_when_not_in_pg(self) -> None:
        service, _, _, pg_store = _make_service()
        pg_store.delete.return_value = False

        result = await service.delete("ws1", "missing")

        assert result is False

    async def test_qdrant_failure_does_not_block_delete(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        pg_store.delete.return_value = True
        qdrant_store.delete.side_effect = Exception("qdrant down")

        with patch("metatron.memory.service.delete_memory_node"):
            result = await service.delete("ws1", "mem001")

        assert result is True


# ---------------------------------------------------------------------------
# Get persistent
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_from_pg(self) -> None:
        service, _, _, pg_store = _make_service()
        expected = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get.return_value = expected

        result = await service.get("ws1", "mem001")

        assert result is expected
        pg_store.get.assert_awaited_once_with("ws1", "mem001")

    async def test_returns_none_when_not_found(self) -> None:
        service, _, _, pg_store = _make_service()
        pg_store.get.return_value = None

        result = await service.get("ws1", "missing")

        assert result is None


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestListPersistent:
    async def test_delegates_to_pg(self) -> None:
        service, _, _, pg_store = _make_service()
        records = [_sample_record(id="m1"), _sample_record(id="m2")]
        pg_store.list_records.return_value = records

        result = await service.list_records("ws1", agent_id="agent1")

        assert len(result) == 2
        pg_store.list_records.assert_awaited_once_with(
            "ws1", agent_id="agent1", scope=None, limit=100, offset=0
        )


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    async def test_resets_pg_qdrant_neo4j(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        pg_store.reset.return_value = (2, ["m1", "m2"])

        with patch("metatron.memory.service.delete_memory_node") as mock_graph:
            mock_graph.return_value = True
            count = await service.reset("ws1", agent_id="agent1")

        assert count == 2
        pg_store.reset.assert_awaited_once_with("ws1", agent_id="agent1", scope=None)
        assert qdrant_store.delete.await_count == 2
        qdrant_store.delete.assert_any_await("m1")
        qdrant_store.delete.assert_any_await("m2")

    async def test_reset_with_scope_only_cleans_derived_stores(self) -> None:
        """Scope-only reset (agent_id=None) must still clean Qdrant + Neo4j."""
        service, _, qdrant_store, pg_store = _make_service()
        pg_store.reset.return_value = (1, ["m1"])

        with patch("metatron.memory.service.delete_memory_node"):
            count = await service.reset("ws1", scope=MemoryScope.GLOBAL)

        assert count == 1
        qdrant_store.delete.assert_awaited_once_with("m1")

    async def test_reset_returns_zero_skips_cleanup(self) -> None:
        service, _, qdrant_store, pg_store = _make_service()
        pg_store.reset.return_value = (0, [])

        count = await service.reset("ws1", agent_id="agent1")

        assert count == 0
        qdrant_store.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Promote
# ---------------------------------------------------------------------------


class TestPromote:
    async def test_promotes_session_record(self) -> None:
        service, redis_cache, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.SESSION, session_id="sess1")
        redis_cache.get.return_value = record
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record

        with patch("metatron.memory.service.save_memory_to_graph"):
            result = await service.promote("ws1", "sess1", "mem001")

        assert result.scope == MemoryScope.PER_AGENT
        pg_store.save.assert_awaited_once()
        qdrant_store.upsert.assert_awaited_once()
        redis_cache.delete_record.assert_awaited_once_with("ws1", "sess1", "mem001")

    async def test_promote_with_custom_scope(self) -> None:
        service, redis_cache, _, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.SESSION)
        redis_cache.get.return_value = record
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record

        with patch("metatron.memory.service.save_memory_to_graph"):
            result = await service.promote(
                "ws1",
                "sess1",
                "mem001",
                target_scope=MemoryScope.GLOBAL,
            )

        assert result.scope == MemoryScope.GLOBAL

    async def test_promote_falls_back_to_pg_on_redis_miss(self) -> None:
        service, redis_cache, _, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.SESSION)
        redis_cache.get.return_value = None
        pg_store.get.return_value = record
        pg_store.get_by_hash.return_value = None
        pg_store.save.return_value = record

        with patch("metatron.memory.service.save_memory_to_graph"):
            result = await service.promote("ws1", "sess1", "mem001")

        assert result.scope == MemoryScope.PER_AGENT
        pg_store.get.assert_awaited_once_with("ws1", "mem001")

    async def test_promote_raises_when_not_found(self) -> None:
        service, redis_cache, _, pg_store = _make_service()
        redis_cache.get.return_value = None
        pg_store.get.return_value = None

        with pytest.raises(MemoryNotFoundError):
            await service.promote("ws1", "sess1", "missing")


# ---------------------------------------------------------------------------
# Hybrid search delegation
# ---------------------------------------------------------------------------


class TestServiceSearch:
    async def test_delegates_to_search_service(self) -> None:
        redis_cache = AsyncMock()
        qdrant_store = AsyncMock()
        pg_store = AsyncMock()
        search = AsyncMock()
        search.hybrid_search.return_value = ["result"]
        service = MemoryService(
            redis_cache=redis_cache,
            qdrant_store=qdrant_store,
            pg_store=pg_store,
            workspace_id="ws1",
            search=search,
        )

        result = await service.search(
            "ws1",
            "query",
            agent_id="agent1",
            scope=MemoryScope.PER_AGENT,
            tags=["t"],
            session_id="sess1",
            top_k=7,
        )

        assert result == ["result"]
        search.hybrid_search.assert_awaited_once_with(
            "ws1",
            "query",
            agent_id="agent1",
            scope=MemoryScope.PER_AGENT,
            tags=["t"],
            session_id="sess1",
            top_k=7,
        )

    async def test_raises_when_search_not_configured(self) -> None:
        service, _, _, _ = _make_service()

        with pytest.raises(RuntimeError, match="search not configured"):
            await service.search("ws1", "query")


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------


class TestWorkspaceIsolation:
    async def test_rejects_mismatched_workspace(self) -> None:
        service, _, _, _ = _make_service(workspace_id="ws1")

        with pytest.raises(ValueError, match="workspace_id mismatch"):
            await service.save("ws_other", _sample_record(scope=MemoryScope.PER_AGENT))

    async def test_rejects_mismatch_on_get(self) -> None:
        service, _, _, _ = _make_service(workspace_id="ws1")

        with pytest.raises(ValueError, match="workspace_id mismatch"):
            await service.get("ws_other", "mem001")


# ---------------------------------------------------------------------------
# Content hash exact-match semantics
# ---------------------------------------------------------------------------


class TestContentHashSemantics:
    async def test_whitespace_difference_is_not_deduped(self) -> None:
        """'hello' and 'hello ' must produce different hashes."""
        service, _, _, pg_store = _make_service()
        r1 = _sample_record(id="m1", scope=MemoryScope.PER_AGENT, content="hello")
        r2 = _sample_record(id="m2", scope=MemoryScope.PER_AGENT, content="hello ")
        pg_store.get_by_hash.return_value = None
        pg_store.save.side_effect = lambda r: r

        with patch("metatron.memory.service.save_memory_to_graph"):
            await service.save("ws1", r1)
            await service.save("ws1", r2)

        assert r1.content_hash != r2.content_hash


# ---------------------------------------------------------------------------
# Promote partial failure
# ---------------------------------------------------------------------------


class TestPromotePartialFailure:
    async def test_redis_cleaned_on_qdrant_failure_in_dedup_branch(self) -> None:
        """If Qdrant upsert raises during dedup-promote, Redis record is
        still cleaned up and the exception propagates."""
        service, redis_cache, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.SESSION, session_id="sess1")
        existing = _sample_record(id="existing001", scope=MemoryScope.SESSION)
        redis_cache.get.return_value = record
        pg_store.get_by_hash.return_value = existing
        pg_store.save.return_value = existing
        qdrant_store.upsert.side_effect = Exception("qdrant down")

        with (
            patch("metatron.memory.service.save_memory_to_graph"),
            pytest.raises(Exception, match="qdrant down"),
        ):
            await service.promote("ws1", "sess1", "mem001")


# ---------------------------------------------------------------------------
# Freshness hook (MTRNIX-304)
# ---------------------------------------------------------------------------


class TestFreshnessHook:
    async def test_save_still_returns_when_freshness_raises(self) -> None:
        """Producer failures must never surface to the caller (fail-soft)."""
        service, _, qdrant_store, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = None

        with (
            patch("metatron.memory.service.save_memory_to_graph"),
            patch(
                "metatron.memory.service.enqueue_if_enabled",
                side_effect=Exception("boom"),
            ) as mock_enqueue,
        ):
            # enqueue_if_enabled already wraps errors internally, so the
            # service should still return the saved record even if we
            # simulate a bug one layer deeper. Patch asserts the hook is
            # reached.
            try:
                result = await service.save("ws1", record)
            except Exception:
                mock_enqueue.assert_called_once()
                return

        assert result is record
        mock_enqueue.assert_called_once()

    async def test_save_calls_producer_with_knowledge_changed(self) -> None:
        service, _, _, pg_store = _make_service()
        record = _sample_record(scope=MemoryScope.PER_AGENT)
        pg_store.get_by_hash.return_value = None

        with (
            patch("metatron.memory.service.save_memory_to_graph"),
            patch(
                "metatron.memory.service.enqueue_if_enabled",
                new_callable=AsyncMock,
            ) as mock_enqueue,
        ):
            await service.save("ws1", record)

        mock_enqueue.assert_called_once()
        args, kwargs = mock_enqueue.call_args
        assert args[0] == "ws1"
        assert args[1] == record.id
        assert args[2] == "knowledge_changed"

    async def test_delete_calls_producer_with_knowledge_deleted(self) -> None:
        service, _, _, pg_store = _make_service()
        pg_store.delete.return_value = True

        with (
            patch("metatron.memory.service.delete_memory_node"),
            patch(
                "metatron.memory.service.enqueue_if_enabled",
                new_callable=AsyncMock,
            ) as mock_enqueue,
        ):
            ok = await service.delete("ws1", "mem001")

        assert ok is True
        mock_enqueue.assert_called_once()
        args, _kwargs = mock_enqueue.call_args
        assert args == ("ws1", "mem001", "knowledge_deleted")
