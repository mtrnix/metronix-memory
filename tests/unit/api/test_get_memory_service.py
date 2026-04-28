"""Unit tests for get_memory_service DI helper.

Verifies that the REST path wires freshness_store and passes pg_store to
MemorySearchService — closing the parity gap with the MCP path (MTRNIX-324).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from metatron.api.dependencies import get_memory_service
from metatron.core.config import Settings


def _make_request(workspace_id: str = "ws-test") -> MagicMock:
    """Build a minimal mock Request that get_memory_service can consume."""
    settings = Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=False,
        METATRON_SECRET_KEY="test-secret",
    )
    app_state: dict[str, Any] = {"settings": settings}

    _MISSING = object()

    class _State:
        def __getattr__(self, name: str) -> Any:
            val = app_state.get(name, _MISSING)
            if val is _MISSING:
                raise AttributeError(name)
            return val

        def __setattr__(self, name: str, value: Any) -> None:
            app_state[name] = value

    plugin_manager = MagicMock()
    plugin_manager.get_event_bus.return_value = MagicMock()
    app_state["plugin_manager"] = plugin_manager

    request = MagicMock()
    request.app.state = _State()
    request.state.user = {"workspace_ids": [workspace_id]}
    return request


# Because get_memory_service uses lazy (function-body) imports, we patch at
# the source module level, not at `metatron.api.dependencies.<Name>`.
_PATCH_BASES = {
    "pg_store": "metatron.storage.memory_postgres.MemoryPostgresStore",
    "qdrant": "metatron.storage.memory_qdrant.MemoryQdrantStore",
    "redis_session": "metatron.storage.memory_redis.RedisSessionCache",
    "redis_store": "metatron.storage.redis.RedisStore",
    "search": "metatron.memory.search.MemorySearchService",
    "svc": "metatron.memory.service.MemoryService",
    "engine": "sqlalchemy.ext.asyncio.create_async_engine",
    "freshness": "metatron.storage.freshness_pg.FreshnessStore",
}


class TestGetMemoryServiceWiring:
    """Smoke tests — verify DI assembles the service without errors."""

    def test_freshness_store_wired_into_service(self) -> None:
        """get_memory_service must construct a FreshnessStore and pass it."""
        request = _make_request()

        with (
            patch(_PATCH_BASES["pg_store"]) as _pg,
            patch(_PATCH_BASES["qdrant"]) as _qdrant,
            patch(_PATCH_BASES["redis_session"]) as _redis,
            patch(_PATCH_BASES["redis_store"]) as _redis_store,
            patch(_PATCH_BASES["search"]) as _search,
            patch(_PATCH_BASES["svc"]) as _svc,
            patch(_PATCH_BASES["engine"]) as _eng,
            patch(_PATCH_BASES["freshness"]) as _freshness,
        ):
            _eng.return_value = MagicMock()
            _pg.return_value = MagicMock()
            _qdrant.return_value = MagicMock()
            _redis_store.return_value = MagicMock()
            _redis.return_value = MagicMock()
            _search.return_value = MagicMock()
            _freshness.return_value = MagicMock()

            get_memory_service(request)

            # MemoryService must have been called with freshness_store kwarg
            call_kwargs = _svc.call_args.kwargs
            assert "freshness_store" in call_kwargs
            assert call_kwargs["freshness_store"] is not None

    def test_pg_store_passed_to_search_service(self) -> None:
        """MemorySearchService must receive pg_store for graph-leg filtering."""
        request = _make_request()

        with (
            patch(_PATCH_BASES["pg_store"]) as _pg,
            patch(_PATCH_BASES["qdrant"]) as _qdrant,
            patch(_PATCH_BASES["redis_session"]) as _redis,
            patch(_PATCH_BASES["redis_store"]) as _redis_store,
            patch(_PATCH_BASES["search"]) as _search,
            patch(_PATCH_BASES["svc"]),
            patch(_PATCH_BASES["engine"]) as _eng,
            patch(_PATCH_BASES["freshness"]),
        ):
            pg_store_instance = MagicMock()
            _pg.return_value = pg_store_instance
            _eng.return_value = MagicMock()
            _qdrant.return_value = MagicMock()
            _redis_store.return_value = MagicMock()
            _redis.return_value = MagicMock()
            _search.return_value = MagicMock()

            get_memory_service(request)

            # MemorySearchService must have been constructed with pg_store=
            search_call_kwargs = _search.call_args.kwargs
            assert "pg_store" in search_call_kwargs
            assert search_call_kwargs["pg_store"] is pg_store_instance

    def test_freshness_store_cached_on_app_state(self) -> None:
        """Second call within same app must reuse the cached freshness store."""
        request = _make_request()

        with (
            patch(_PATCH_BASES["pg_store"]) as _pg,
            patch(_PATCH_BASES["qdrant"]),
            patch(_PATCH_BASES["redis_session"]) as _redis,
            patch(_PATCH_BASES["redis_store"]) as _redis_store,
            patch(_PATCH_BASES["search"]),
            patch(_PATCH_BASES["svc"]),
            patch(_PATCH_BASES["engine"]) as _eng,
            patch(_PATCH_BASES["freshness"]) as _freshness,
        ):
            _eng.return_value = MagicMock()
            _pg.return_value = MagicMock()
            _redis_store.return_value = MagicMock()
            _redis.return_value = MagicMock()
            freshness_instance = MagicMock()
            _freshness.return_value = freshness_instance

            # First call
            get_memory_service(request)
            # Second call — same workspace should hit the service cache (no
            # reconstruction), but the freshness store should still not be
            # constructed a second time.
            get_memory_service(request)

            # FreshnessStore constructor called exactly once
            assert _freshness.call_count == 1
