"""PostgreSQL-backed user store with bcrypt authentication.

Tables:
    users            — user accounts (email, password_hash, role)
    user_workspaces  — workspace membership
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from metronix.auth.passwords import hash_password

logger = structlog.get_logger(__name__)


class UserStore:
    """CRUD for user accounts and workspace membership."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ensure_schema(self) -> None:
        """Create users and user_workspaces tables if they don't exist.

        Also migrates existing users table (from Alembic/core) by adding
        missing columns if the table already exists without them.
        """
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id            TEXT PRIMARY KEY,
                        username      TEXT NOT NULL DEFAULT '',
                        email         TEXT,
                        password_hash TEXT,
                        display_name  TEXT NOT NULL DEFAULT '',
                        role          TEXT NOT NULL DEFAULT 'viewer',
                        is_active     BOOLEAN NOT NULL DEFAULT true,
                        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at    TIMESTAMPTZ
                    )
                """)
                )
                # Migrate existing table: add columns that may be missing
                for col, col_def in [
                    ("username", "TEXT NOT NULL DEFAULT ''"),
                    ("email", "TEXT"),
                    ("password_hash", "TEXT"),
                    ("display_name", "TEXT NOT NULL DEFAULT ''"),
                    ("is_active", "BOOLEAN NOT NULL DEFAULT true"),
                    ("updated_at", "TIMESTAMPTZ"),
                    ("owui_user_id", "TEXT"),
                ]:
                    # IF NOT EXISTS guards the column, but legacy PG versions
                    # may still raise — swallow harmlessly.
                    with contextlib.suppress(Exception):
                        await conn.execute(
                            text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {col_def}")
                        )
                # Ensure unique constraint on email
                with contextlib.suppress(Exception):
                    await conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email) WHERE email IS NOT NULL"  # noqa: E501
                        )
                    )
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS user_workspaces (
                        user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        workspace_id TEXT NOT NULL,
                        joined_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (user_id, workspace_id)
                    )
                """)
                )
            else:
                # SQLite (tests)
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id            TEXT PRIMARY KEY,
                        username      TEXT NOT NULL DEFAULT '',
                        email         TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        display_name  TEXT NOT NULL DEFAULT '',
                        role          TEXT NOT NULL DEFAULT 'viewer',
                        is_active     INTEGER NOT NULL DEFAULT 1,
                        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at    TEXT,
                        owui_user_id  TEXT
                    )
                """)
                )
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS user_workspaces (
                        user_id      TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        joined_at    TEXT NOT NULL DEFAULT (datetime('now')),
                        PRIMARY KEY (user_id, workspace_id)
                    )
                """)
                )
        logger.info("user_store.schema.ensured", dialect=dialect)

    # -- Users ---------------------------------------------------------------

    async def create_user(
        self,
        email: str,
        password: str,
        display_name: str = "",
        role: str = "viewer",
        workspace_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        user_id = str(uuid4())
        pw_hash = hash_password(password)
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO users (id, username, email, password_hash, display_name, role)
                    VALUES (:id, :username, :email, :pw_hash, :display_name, :role)
                """),
                {
                    "id": user_id,
                    "username": email.split("@")[0],
                    "email": email,
                    "pw_hash": pw_hash,
                    "display_name": display_name,
                    "role": role,
                },
            )
            for ws_id in workspace_ids or []:
                await conn.execute(
                    text("""
                        INSERT INTO user_workspaces (user_id, workspace_id)
                        VALUES (:uid, :ws)
                    """),
                    {"uid": user_id, "ws": ws_id},
                )
        logger.info("user_store.user.created", email=email, role=role)
        return {
            "id": user_id,
            "email": email,
            "display_name": display_name,
            "role": role,
            "is_active": True,
            "workspace_ids": workspace_ids or [],
        }

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, email, password_hash, display_name, role, is_active, created_at FROM users WHERE email = :email"  # noqa: E501
                    ),
                    {"email": email},
                )
            ).first()
            if not row:
                return None
            user = dict(row._mapping)
            user["workspace_ids"] = await self.get_user_workspaces(user["id"])
            return user

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, email, display_name, role, is_active, created_at, updated_at, owui_user_id FROM users WHERE id = :id"  # noqa: E501
                    ),
                    {"id": user_id},
                )
            ).first()
            if not row:
                return None
            user = dict(row._mapping)
            user["workspace_ids"] = await self.get_user_workspaces(user_id)
            return user

    async def list_users(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        async with self._engine.connect() as conn:
            total_row = (await conn.execute(text("SELECT COUNT(*) FROM users"))).scalar()
            rows = await conn.execute(
                text(
                    "SELECT id, email, display_name, role, is_active, created_at FROM users ORDER BY created_at LIMIT :limit OFFSET :offset"  # noqa: E501
                ),
                {"limit": limit, "offset": offset},
            )
            users = []
            for row in rows:
                user = dict(row._mapping)
                user["workspace_ids"] = await self.get_user_workspaces(user["id"])
                users.append(user)
            return users, total_row or 0

    async def update_user(self, user_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return await self.get_user_by_id(user_id)
        # Handle password separately
        if "password" in fields:
            fields["password_hash"] = hash_password(fields.pop("password"))
        allowed = {"email", "password_hash", "display_name", "role", "is_active", "owui_user_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return await self.get_user_by_id(user_id)
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = user_id
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                set_clause += ", updated_at = NOW()"
            else:
                set_clause += ", updated_at = datetime('now')"
            result = await conn.execute(
                text(f"UPDATE users SET {set_clause} WHERE id = :id"),
                updates,
            )
            if result.rowcount == 0:
                return None
        return await self.get_user_by_id(user_id)

    async def delete_user(self, user_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": user_id},
            )
            return result.rowcount > 0

    # -- Workspaces ----------------------------------------------------------

    async def get_user_workspaces(self, user_id: str) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT workspace_id FROM user_workspaces WHERE user_id = :uid"),
                {"uid": user_id},
            )
            return [r[0] for r in rows]

    async def add_workspace(self, user_id: str, workspace_id: str) -> None:
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                await conn.execute(
                    text("""
                        INSERT INTO user_workspaces (user_id, workspace_id)
                        VALUES (:uid, :ws) ON CONFLICT DO NOTHING
                    """),
                    {"uid": user_id, "ws": workspace_id},
                )
            else:
                await conn.execute(
                    text("""
                        INSERT OR IGNORE INTO user_workspaces (user_id, workspace_id)
                        VALUES (:uid, :ws)
                    """),
                    {"uid": user_id, "ws": workspace_id},
                )

    async def remove_workspace(self, user_id: str, workspace_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM user_workspaces WHERE user_id = :uid AND workspace_id = :ws"),
                {"uid": user_id, "ws": workspace_id},
            )

    # -- Seed ----------------------------------------------------------------

    async def seed_admin(self, password: str) -> dict[str, Any] | None:
        """Create initial admin user if users table is empty.

        Handles multi-replica race conditions: if another replica already
        created the admin between the COUNT check and INSERT, the
        IntegrityError is caught and treated as a no-op.
        """
        async with self._engine.connect() as conn:
            count = (await conn.execute(text("SELECT COUNT(*) FROM users"))).scalar()
            if count and count > 0:
                return None

        try:
            user = await self.create_user(
                email="admin@metronix.local",
                password=password,
                display_name="Admin",
                role="admin",
            )
        except Exception:
            # Another replica already created the admin — not an error
            return None
        # Add to all existing workspaces
        try:
            async with self._engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT workspace_id FROM workspaces"),
                )
                for row in rows:
                    await self.add_workspace(user["id"], row[0])
                user["workspace_ids"] = await self.get_user_workspaces(user["id"])
        except Exception:
            # workspaces table might not exist yet
            pass

        logger.info("user_store.admin.seeded", email="admin@metronix.local")
        return user
