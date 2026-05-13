"""Unit tests for MemoryService session dual-write + lifetime forwarding (Phase 2).

Covers:
* MS1 — cache_session populates ttl_expires_at from default memory_session_ttl
* MS2 — cache_session honours explicit ttl_seconds override
* MS3 — cache_session PG write success (pg_store.save called once)
* MS4 — cache_session PG write raises — Redis still succeeds, warning logged
* MS5 — cache_session Redis raises — exception propagates, pg_store.save never called
* MS6 — list_records(lifetime=...) forwards kwarg to pg_store
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import (
    LifecycleStatus,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)
from metatron.memory.service import MemoryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(record_id: str = "mem-001", session_id: str | None = None) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id="ws1",
        agent_id="agent1",
        scope=MemoryScope.SESSION,
        source_type="conversation",
        content="hello world",
        tags=[],
        importance_score=0.5,
        ttl_expires_at=None,
        content_hash="abc",
        session_id=session_id,
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=MemoryStatus.ACTIVE,
    )


def _make_service(
    *,
    redis_side_effect: Exception | None = None,
    pg_save_side_effect: Exception | None = None,
) -> tuple[MemoryService, dict]:
    pg = MagicMock()
    pg.save = AsyncMock(side_effect=pg_save_side_effect)
    pg.list_records = AsyncMock(return_value=[])
    qdrant = MagicMock()
    redis = MagicMock()

    if redis_side_effect is not None:
        redis.cache = AsyncMock(side_effect=redis_side_effect)
    else:
        # Redis cache returns the same record with session_id set.
        async def _cache_ok(ws, session_id, record, *, ttl_seconds=None):  # type: ignore[no-untyped-def]  # noqa: ANN001, ANN202
            return record

        redis.cache = AsyncMock(side_effect=_cache_ok)

    service = MemoryService(
        redis_cache=redis,
        qdrant_store=qdrant,
        pg_store=pg,
        workspace_id="ws1",
    )
    return service, {"pg": pg, "qdrant": qdrant, "redis": redis}


# ---------------------------------------------------------------------------
# MS1 — ttl_expires_at populated from default setting
# ---------------------------------------------------------------------------


class TestCacheSessionTtlPopulation:
    async def test_ms1_default_ttl_populates_ttl_expires_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ttl_expires_at is set to now + memory_session_ttl when not provided."""
        from metatron.core import config as config_mod

        fake_settings = MagicMock()
        fake_settings.memory_session_ttl = 3600  # 1 hour
        monkeypatch.setattr(config_mod, "get_settings", lambda: fake_settings)

        service, mocks = _make_service()
        record = _record()
        before = datetime.now(UTC)
        await service.cache_session("ws1", "sess-1", record)
        after = datetime.now(UTC)

        assert record.session_id == "sess-1"
        assert record.ttl_expires_at is not None
        expected_lower = before + timedelta(seconds=3600) - timedelta(seconds=1)
        expected_upper = after + timedelta(seconds=3600) + timedelta(seconds=1)
        assert expected_lower <= record.ttl_expires_at <= expected_upper

    async def test_ms2_explicit_ttl_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit ttl_seconds=600 sets ttl_expires_at ≈ now+600s."""
        from metatron.core import config as config_mod

        fake_settings = MagicMock()
        fake_settings.memory_session_ttl = 14400  # would be 4h if used
        monkeypatch.setattr(config_mod, "get_settings", lambda: fake_settings)

        service, _ = _make_service()
        record = _record()
        before = datetime.now(UTC)
        await service.cache_session("ws1", "sess-1", record, ttl_seconds=600)
        after = datetime.now(UTC)

        assert record.ttl_expires_at is not None
        expected_lower = before + timedelta(seconds=600) - timedelta(seconds=1)
        expected_upper = after + timedelta(seconds=600) + timedelta(seconds=1)
        assert expected_lower <= record.ttl_expires_at <= expected_upper


# ---------------------------------------------------------------------------
# MS3 — PG write success
# ---------------------------------------------------------------------------


class TestCacheSessionPgWriteSuccess:
    async def test_ms3_pg_save_called_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When Redis succeeds, pg_store.save is awaited exactly once."""
        from metatron.core import config as config_mod

        fake_settings = MagicMock()
        fake_settings.memory_session_ttl = 3600
        monkeypatch.setattr(config_mod, "get_settings", lambda: fake_settings)

        service, mocks = _make_service()
        record = _record()
        await service.cache_session("ws1", "sess-1", record)

        mocks["pg"].save.assert_awaited_once_with(record)


# ---------------------------------------------------------------------------
# MS4 — PG write raises — Redis still succeeds
# ---------------------------------------------------------------------------


class TestCacheSessionPgFailure:
    async def test_ms4_pg_down_does_not_block_redis(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PG failure is swallowed; warning logged; Redis result returned."""
        import metatron.memory.service as svc_mod
        from metatron.core import config as config_mod

        fake_settings = MagicMock()
        fake_settings.memory_session_ttl = 3600
        monkeypatch.setattr(config_mod, "get_settings", lambda: fake_settings)

        service, mocks = _make_service(pg_save_side_effect=RuntimeError("pg down"))
        record = _record()

        # Patch the structlog logger object on the service module to capture warnings.
        mock_logger = MagicMock()
        monkeypatch.setattr(svc_mod, "logger", mock_logger)

        result = await service.cache_session("ws1", "sess-1", record)

        # Redis result returned normally.
        assert result is record
        # Warning was emitted via structlog logger.
        assert mock_logger.warning.called
        # The first positional arg to any warning call should match our event.
        warning_events = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert any("memory.session.pg_write_failed" in ev for ev in warning_events)


# ---------------------------------------------------------------------------
# MS5 — Redis raises — propagates, PG never called
# ---------------------------------------------------------------------------


class TestCacheSessionRedisFailure:
    async def test_ms5_redis_failure_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When Redis raises, the exception propagates; pg_store.save is NOT called."""
        from metatron.core import config as config_mod

        fake_settings = MagicMock()
        fake_settings.memory_session_ttl = 3600
        monkeypatch.setattr(config_mod, "get_settings", lambda: fake_settings)

        service, mocks = _make_service(redis_side_effect=ConnectionError("redis down"))
        record = _record()

        with pytest.raises(ConnectionError):
            await service.cache_session("ws1", "sess-1", record)

        mocks["pg"].save.assert_not_awaited()


# ---------------------------------------------------------------------------
# MS6 — list_records forwards lifetime kwarg
# ---------------------------------------------------------------------------


class TestListRecordsLifetimeForwarding:
    async def test_ms6_lifetime_forwarded_to_pg_store(self) -> None:
        """list_records(lifetime='session') forwards the kwarg to pg_store.list_records."""
        pg = MagicMock()
        pg.list_records = AsyncMock(return_value=[])
        service = MemoryService(
            redis_cache=MagicMock(),
            qdrant_store=MagicMock(),
            pg_store=pg,
            workspace_id="ws1",
        )

        await service.list_records("ws1", lifetime="session")

        pg.list_records.assert_awaited_once()
        call_kwargs = pg.list_records.call_args.kwargs
        assert call_kwargs["lifetime"] == "session"
