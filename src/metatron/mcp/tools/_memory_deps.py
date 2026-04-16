"""MemoryService construction helper for MCP tools.

MCP tools run outside the FastAPI request scope, so they cannot reuse
``api.dependencies.get_memory_service``. This module mirrors that lazy
construction logic with a module-level cache keyed by workspace_id.

Underscore prefix intentional — this module is internal to ``mcp/tools``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from metatron.core.config import get_settings

if TYPE_CHECKING:
    from metatron.memory.service import MemoryService


# Per-workspace cache of MemoryService instances.
# TODO: wire disposal in lifespan shutdown — Redis/PG engines currently leak.
_SERVICES: dict[str, MemoryService] = {}
_LOCK = asyncio.Lock()


async def build_memory_service_for_workspace(workspace_id: str) -> MemoryService:
    """Return (and lazily construct) a MemoryService for ``workspace_id``.

    Unlike ``api.dependencies.get_memory_service`` which stashes shared
    resources on ``app.state``, this helper uses a module-level dict guarded
    by an ``asyncio.Lock`` so concurrent tool calls do not double-construct
    expensive backends.
    """
    cached = _SERVICES.get(workspace_id)
    if cached is not None:
        return cached

    async with _LOCK:
        cached = _SERVICES.get(workspace_id)
        if cached is not None:
            return cached

        from sqlalchemy.ext.asyncio import create_async_engine

        from metatron.memory.search import MemorySearchService
        from metatron.memory.service import MemoryService
        from metatron.storage.memory_postgres import MemoryPostgresStore
        from metatron.storage.memory_qdrant import MemoryQdrantStore
        from metatron.storage.memory_redis import RedisSessionCache
        from metatron.storage.redis import RedisStore

        settings = get_settings()

        redis_store = RedisStore(settings.redis_url)
        redis_cache = RedisSessionCache(
            redis_store,
            default_ttl=settings.memory_session_ttl,
        )

        engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        pg_store = MemoryPostgresStore(engine)

        qdrant_store = MemoryQdrantStore(
            workspace_id=workspace_id,
            host=settings.qdrant_host,
            port=settings.qdrant_http_port,
        )
        search = MemorySearchService(qdrant=qdrant_store, redis=redis_cache)

        service = MemoryService(
            redis_cache=redis_cache,
            qdrant_store=qdrant_store,
            pg_store=pg_store,
            workspace_id=workspace_id,
            search=search,
        )

        _SERVICES[workspace_id] = service
        return service


def _reset_cache_for_tests() -> None:
    """Clear the service cache. Intended for unit tests only."""
    _SERVICES.clear()
