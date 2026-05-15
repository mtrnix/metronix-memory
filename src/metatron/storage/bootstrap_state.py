"""BootstrapStateStore — async DAO for the bootstrap_state table (MTRNIX-352, T2).

All methods use parameterised SQLAlchemy text() queries — no ORM, no raw string
concatenation. Engine is injected at construction: no global state.

Workspace isolation: every write and read is keyed by workspace_id (the PK).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — used in method signatures at runtime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine  # noqa: TC002 — constructor parameter type

from metatron.workspaces.bootstrap.models import BootstrapState, BootstrapStateEnum

logger = structlog.get_logger(__name__)


def _row_to_state(row: Any) -> BootstrapState:  # noqa: ANN401
    m = row._mapping
    return BootstrapState(
        workspace_id=str(m["workspace_id"]),
        state=BootstrapStateEnum(str(m["state"])),
        progress=float(m["progress"]),
        current_step=m.get("current_step"),
        last_processed_resource=m.get("last_processed_resource"),
        last_processed_id=m.get("last_processed_id"),
        indexed_count=int(m["indexed_count"]),
        total_count=m.get("total_count"),
        last_error=m.get("last_error"),
        last_synced_at=m.get("last_synced_at"),
        retry_count=int(m["retry_count"]),
        next_retry_at=m.get("next_retry_at"),
        updated_at=m["updated_at"],
    )


class BootstrapStateStore:
    """Async DAO for the ``bootstrap_state`` table.

    Parameters
    ----------
    engine:
        An already-configured :class:`~sqlalchemy.ext.asyncio.AsyncEngine`.
        This class does not create or close the engine — that is the caller's
        responsibility.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, workspace_id: str) -> BootstrapState | None:
        """Fetch the bootstrap state row for *workspace_id*. Returns None on miss."""
        sql = text("SELECT * FROM bootstrap_state WHERE workspace_id = :w")
        async with self._engine.connect() as conn:
            result = await conn.execute(sql, {"w": workspace_id})
            row = result.first()
        if row is None:
            return None
        return _row_to_state(row)

    async def upsert_initial(
        self,
        workspace_id: str,
        *,
        total_count: int | None = None,
    ) -> BootstrapState:
        """Insert a new bootstrapping row or no-op if already exists.

        The ON CONFLICT UPDATE no-op forces RETURNING to fire on conflict so we
        always get the current row back in a single round-trip.
        """
        sql = text("""
            INSERT INTO bootstrap_state (workspace_id, state, total_count)
            VALUES (:w, 'bootstrapping', :t)
            ON CONFLICT (workspace_id) DO UPDATE
                SET workspace_id = EXCLUDED.workspace_id
            RETURNING *
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"w": workspace_id, "t": total_count})
            row = result.first()
        assert row is not None, "RETURNING must yield a row"
        return _row_to_state(row)

    async def update_checkpoint(
        self,
        workspace_id: str,
        *,
        current_step: str | None = None,
        last_processed_resource: str | None = None,
        last_processed_id: str | None = None,
        indexed_count: int | None = None,
        progress: float | None = None,
        total_count: int | None = None,
    ) -> None:
        """Partial-update checkpoint fields. Only non-None columns are written.

        Always sets ``updated_at = NOW()``.
        """
        parts: list[str] = ["updated_at = NOW()"]
        params: dict[str, Any] = {"w": workspace_id}

        if current_step is not None:
            parts.append("current_step = :current_step")
            params["current_step"] = current_step
        if last_processed_resource is not None:
            parts.append("last_processed_resource = :lpr")
            params["lpr"] = last_processed_resource
        if last_processed_id is not None:
            parts.append("last_processed_id = :lpid")
            params["lpid"] = last_processed_id
        if indexed_count is not None:
            parts.append("indexed_count = :ic")
            params["ic"] = indexed_count
        if progress is not None:
            parts.append("progress = :prog")
            params["prog"] = progress
        if total_count is not None:
            parts.append("total_count = :tc")
            params["tc"] = total_count

        set_clause = ", ".join(parts)
        sql = text(f"UPDATE bootstrap_state SET {set_clause} WHERE workspace_id = :w")  # noqa: S608
        async with self._engine.begin() as conn:
            await conn.execute(sql, params)

    async def set_state(
        self,
        workspace_id: str,
        *,
        state: BootstrapStateEnum,
        clear_error: bool = False,
    ) -> None:
        """Update the state column (and optionally clear last_error)."""
        parts = ["state = :s", "updated_at = NOW()"]
        if clear_error:
            parts.append("last_error = NULL")
        set_clause = ", ".join(parts)
        sql = text(
            f"UPDATE bootstrap_state SET {set_clause} WHERE workspace_id = :w"  # noqa: S608
        )
        async with self._engine.begin() as conn:
            await conn.execute(sql, {"s": str(state), "w": workspace_id})

    async def set_failed(
        self,
        workspace_id: str,
        *,
        last_error: str,
        next_retry_at: datetime | None,
        increment_retry: bool = True,
    ) -> None:
        """Transition to ``failed`` and schedule the next retry attempt."""
        if increment_retry:
            retry_clause = "retry_count = retry_count + 1"
        else:
            retry_clause = "retry_count = retry_count"
        sql = text(f"""
            UPDATE bootstrap_state
            SET state = 'failed',
                last_error = :e,
                next_retry_at = :n,
                {retry_clause},
                updated_at = NOW()
            WHERE workspace_id = :w
        """)
        async with self._engine.begin() as conn:
            await conn.execute(sql, {"e": last_error, "n": next_retry_at, "w": workspace_id})

    async def reset_retry(self, workspace_id: str) -> None:
        """Reset retry_count, next_retry_at, and last_error to zero/null."""
        sql = text("""
            UPDATE bootstrap_state
            SET retry_count = 0,
                next_retry_at = NULL,
                last_error = NULL,
                updated_at = NOW()
            WHERE workspace_id = :w
        """)
        async with self._engine.begin() as conn:
            await conn.execute(sql, {"w": workspace_id})

    async def list_failed_ready_for_retry(
        self,
        *,
        now: datetime,
        max_attempts: int,
        limit: int = 100,
    ) -> list[BootstrapState]:
        """Return failed rows whose retry timer has expired and attempt count is below cap."""
        sql = text("""
            SELECT * FROM bootstrap_state
            WHERE state = 'failed'
              AND next_retry_at IS NOT NULL
              AND next_retry_at <= :now
              AND retry_count < :max
            ORDER BY next_retry_at ASC
            LIMIT :limit
        """)
        async with self._engine.connect() as conn:
            result = await conn.execute(sql, {"now": now, "max": max_attempts, "limit": limit})
            rows = result.fetchall()
        return [_row_to_state(r) for r in rows]

    async def delete(self, workspace_id: str) -> bool:
        """Delete the bootstrap_state row. Returns True if a row was deleted."""
        sql = text(
            "DELETE FROM bootstrap_state WHERE workspace_id = :w RETURNING workspace_id"
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"w": workspace_id})
            row = result.first()
        return row is not None

    async def cas_set_state(
        self,
        workspace_id: str,
        *,
        from_state: BootstrapStateEnum,
        to_state: BootstrapStateEnum,
    ) -> bool:
        """Compare-and-swap state transition.

        Returns True if the row was updated (CAS succeeded), False if another
        worker already changed the state (CAS lost — caller should skip).
        """
        sql = text("""
            UPDATE bootstrap_state
            SET state = :to, updated_at = NOW()
            WHERE workspace_id = :w AND state = :from
            RETURNING workspace_id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                sql, {"to": str(to_state), "w": workspace_id, "from": str(from_state)}
            )
            row = result.first()
        return row is not None

    async def find_stale_bootstrapping(self, *, stale_threshold: datetime) -> list[str]:
        """Return workspace_ids stuck in 'bootstrapping' older than *stale_threshold*.

        Used by :meth:`BootstrapRunner.reclaim_stale_bootstrapping` at startup to
        mark crash-orphaned rows as failed so the retry cron can pick them up.
        """
        sql = text("""
            SELECT workspace_id FROM bootstrap_state
            WHERE state = 'bootstrapping'
              AND updated_at < :threshold
        """)
        async with self._engine.connect() as conn:
            result = await conn.execute(sql, {"threshold": stale_threshold})
            rows = result.fetchall()
        return [str(r._mapping["workspace_id"]) for r in rows]
