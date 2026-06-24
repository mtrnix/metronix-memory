from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from metronix.export.models import ExportJob, ExportScope, ExportStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_COLS = (
    "id, scope, scope_key, status, workspace_count, agent_count, "
    "memory_record_count, document_count, size_bytes, archive_path, download_token, "
    "error, created_at, updated_at"
)


def _row_to_job(m: Any) -> ExportJob:
    scope = m["scope"]
    if isinstance(scope, str):
        scope = json.loads(scope)
    return ExportJob(
        id=m["id"],
        scope=ExportScope.from_dict(scope or {}),
        status=ExportStatus(m["status"]),
        workspace_count=m["workspace_count"],
        agent_count=m["agent_count"],
        memory_record_count=m["memory_record_count"],
        document_count=m["document_count"],
        size_bytes=m["size_bytes"],
        archive_path=m["archive_path"],
        download_token=m["download_token"],
        error=m["error"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


class ExportJobStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, job: ExportJob) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO export_jobs (id, scope, scope_key, status) "
                    "VALUES (:id, CAST(:scope AS jsonb), :scope_key, :status)"
                ),
                {
                    "id": job.id,
                    "scope": json.dumps(job.scope.to_dict()),
                    "scope_key": job.scope.key(),
                    "status": str(job.status),
                },
            )

    async def get(self, export_id: str) -> ExportJob | None:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"SELECT {_COLS} FROM export_jobs WHERE id = :id"),
                {"id": export_id},
            )
            row = result.fetchone()
        return _row_to_job(row._mapping) if row else None

    async def set_status(
        self, export_id: str, status: ExportStatus, *, error: str | None = None
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE export_jobs SET status = :status, error = :error, "
                    "updated_at = NOW() WHERE id = :id"
                ),
                {"id": export_id, "status": str(status), "error": error},
            )

    async def set_result(
        self,
        export_id: str,
        *,
        workspace_count: int,
        agent_count: int,
        memory_record_count: int,
        document_count: int,
        size_bytes: int,
        archive_path: str,
        download_token: str,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE export_jobs SET workspace_count = :wc, agent_count = :ac, "
                    "memory_record_count = :mc, document_count = :dc, size_bytes = :sb, "
                    "archive_path = :path, download_token = :token, updated_at = NOW() "
                    "WHERE id = :id"
                ),
                {
                    "id": export_id,
                    "wc": workspace_count,
                    "ac": agent_count,
                    "mc": memory_record_count,
                    "dc": document_count,
                    "sb": size_bytes,
                    "path": archive_path,
                    "token": download_token,
                },
            )

    async def find_active_for_scope(self, scope: ExportScope) -> ExportJob | None:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"SELECT {_COLS} FROM export_jobs "
                    "WHERE scope_key = :k AND status IN ('pending','running') "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"k": scope.key()},
            )
            row = result.fetchone()
        return _row_to_job(row._mapping) if row else None

    async def reap_orphaned(self, older_than_seconds: int) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE export_jobs SET status = 'failed', "
                    "error = 'reaped: running past watchdog timeout', updated_at = NOW() "
                    "WHERE status IN ('pending','running') "
                    "AND updated_at < NOW() - make_interval(secs => :secs)"
                ),
                {"secs": older_than_seconds},
            )
            return result.rowcount or 0
