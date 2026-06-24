from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from metronix.export.jobs import ExportJobStore
from metronix.export.service import ExportService
from metronix.export.tokens import ExportTokenStore
from metronix.storage.memory_postgres import MemoryPostgresStore
from metronix.storage.postgres import PostgresStore
from metronix.storage.redis import RedisStore

if TYPE_CHECKING:
    from metronix.core.config import Settings


class RegisteredAgentsReader:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def registered_agent_ids(self, ws: str) -> set[str]:
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text("SELECT id FROM agents WHERE workspace_id = :ws"), {"ws": ws}
                )
                return {str(r[0]) for r in result.fetchall()}
        except Exception:  # noqa: BLE001 — agents table optional; flag is best-effort
            return set()


_SERVICE: ExportService | None = None


def build_export_service(settings: Settings) -> ExportService:
    global _SERVICE  # noqa: PLW0603
    if _SERVICE is not None:
        return _SERVICE

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_doc_store = PostgresStore(settings.postgres_dsn)
    mem_store = MemoryPostgresStore(engine)
    redis_store = RedisStore(settings.redis_url)

    _SERVICE = ExportService(
        memory=mem_store,
        docs=pg_doc_store,
        registry=RegisteredAgentsReader(engine),
        job_store=ExportJobStore(engine),
        token_store=ExportTokenStore(redis_store, settings.export_token_ttl_seconds),
        archive_dir=settings.export_dir,
        public_base_url=settings.public_base_url,
        disk_cap_bytes=settings.export_disk_cap_bytes,
    )
    return _SERVICE
