"""Platform user mapping — resolves channel identities to internal users.

When a message arrives from Telegram, Slack, or Discord, we need to map
the platform user ID to an internal User object. This module handles
that lookup, caching, and optional auto-creation.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from metronix.auth.user_store import UserStore
from metronix.core.events import USER_CREATED
from metronix.core.models import Role, User

logger = structlog.get_logger()

_CACHE_TTL_SECONDS = 30.0


def _dict_to_user(d: dict[str, Any]) -> User:
    """Convert a UserStore dict to a core User model."""
    return User(
        id=d["id"],
        username=d.get("email", "").split("@")[0],
        email=d.get("email", ""),
        role=Role(d.get("role", "viewer")),
        workspace_ids=d.get("workspace_ids", []),
    )


class PlatformUserMapper:
    """Maps (channel, channel_user_id, workspace_id) to internal Users.

    Maintains an in-memory TTL cache (30s) following the same pattern
    as enterprise GroupStore.get_user_groups().
    """

    def __init__(self, engine: AsyncEngine, user_store: UserStore) -> None:
        self._engine = engine
        self._user_store = user_store
        self._cache: dict[tuple[str, str, str], tuple[float, User]] = {}

    async def ensure_schema(self) -> None:
        """Create user_platform_mappings table if it doesn't exist."""
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS user_platform_mappings (
                        channel          TEXT NOT NULL,
                        channel_user_id  TEXT NOT NULL,
                        workspace_id     TEXT NOT NULL,
                        user_id          TEXT NOT NULL,
                        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (channel, channel_user_id, workspace_id)
                    )
                """)
                )
            else:
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS user_platform_mappings (
                        channel          TEXT NOT NULL,
                        channel_user_id  TEXT NOT NULL,
                        workspace_id     TEXT NOT NULL,
                        user_id          TEXT NOT NULL,
                        created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                        UNIQUE (channel, channel_user_id, workspace_id)
                    )
                """)
                )
        logger.info("user_mapping.schema.ensured")

    async def map_platform_user(
        self,
        channel: str,
        channel_user_id: str,
        workspace_id: str,
        event_bus: Any | None = None,
        display_name: str = "",
        auto_create: bool = True,
    ) -> User | None:
        """Map a platform identity to an internal user.

        Args:
            channel: Platform name ("telegram", "slack", "discord").
            channel_user_id: Platform-specific user identifier.
            workspace_id: Workspace to scope the mapping.
            event_bus: Optional EventBus to emit USER_CREATED.
            display_name: Display name from the platform (used on auto-create).
            auto_create: If True, create a viewer account on first contact.

        Returns:
            Internal User object, or None if not found and auto_create=False.
        """
        cache_key = (channel, channel_user_id, workspace_id)

        # 1. Check cache
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

        # 2. DB lookup
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("""
                    SELECT user_id FROM user_platform_mappings
                    WHERE channel = :channel
                      AND channel_user_id = :cuid
                      AND workspace_id = :ws
                """),
                    {"channel": channel, "cuid": channel_user_id, "ws": workspace_id},
                )
            ).first()

        if row:
            user_dict = await self._user_store.get_user_by_id(row[0])
            if user_dict:
                user = _dict_to_user(user_dict)
                self._cache[cache_key] = (time.monotonic(), user)
                return user

        # 3. Not found
        if not auto_create:
            return None

        # 4. Auto-create viewer
        synthetic_email = f"{channel}_{channel_user_id}_{workspace_id}@platform.metronix.local"
        random_pw = secrets.token_urlsafe(32)

        user_dict = await self._user_store.create_user(
            email=synthetic_email,
            password=random_pw,
            display_name=display_name,
            role="viewer",
            workspace_ids=[workspace_id],
        )

        # Insert mapping (ON CONFLICT for race condition)
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            params = {
                "channel": channel,
                "cuid": channel_user_id,
                "ws": workspace_id,
                "uid": user_dict["id"],
            }
            if dialect == "postgresql":
                result = await conn.execute(
                    text("""
                        INSERT INTO user_platform_mappings
                            (channel, channel_user_id, workspace_id, user_id)
                        VALUES (:channel, :cuid, :ws, :uid)
                        ON CONFLICT (channel, channel_user_id, workspace_id) DO NOTHING
                    """),
                    params,
                )
            else:
                result = await conn.execute(
                    text("""
                        INSERT OR IGNORE INTO user_platform_mappings
                            (channel, channel_user_id, workspace_id, user_id)
                        VALUES (:channel, :cuid, :ws, :uid)
                    """),
                    params,
                )

            # Race condition: another request created the mapping first.
            # Re-SELECT to get the winner's user_id.
            if result.rowcount == 0:
                winner_row = (
                    await conn.execute(
                        text("""
                        SELECT user_id FROM user_platform_mappings
                        WHERE channel = :channel
                          AND channel_user_id = :cuid
                          AND workspace_id = :ws
                    """),
                        params,
                    )
                ).first()
                if winner_row:
                    winner_dict = await self._user_store.get_user_by_id(winner_row[0])
                    if winner_dict:
                        user = _dict_to_user(winner_dict)
                        self._cache[cache_key] = (time.monotonic(), user)
                        return user

        user = _dict_to_user(user_dict)
        self._cache[cache_key] = (time.monotonic(), user)

        logger.info(
            "user_mapping.auto_created",
            channel=channel,
            channel_user_id=channel_user_id,
            user_id=user.id,
            workspace_id=workspace_id,
        )

        # Emit event
        if event_bus is not None:
            await event_bus.emit(
                USER_CREATED,
                {
                    "user_id": user.id,
                    "workspace_id": workspace_id,
                    "channel": channel,
                    "channel_user_id": channel_user_id,
                    "display_name": display_name,
                    "role": "viewer",
                    "auto_created": True,
                },
            )

        return user

    # ------------------------------------------------------------------
    # Admin CRUD
    # ------------------------------------------------------------------

    async def list_mappings(
        self,
        workspace_id: str,
        channel: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Paginated list of mappings for a workspace."""
        params: dict[str, Any] = {
            "ws": workspace_id,
            "limit": limit,
            "offset": offset,
        }
        where = "WHERE workspace_id = :ws"
        if channel:
            where += " AND channel = :channel"
            params["channel"] = channel

        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(f"""
                    SELECT channel, channel_user_id, workspace_id,
                           user_id, created_at
                    FROM user_platform_mappings
                    {where}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                    params,
                )
            ).fetchall()

        return [
            {
                "channel": r[0],
                "channel_user_id": r[1],
                "workspace_id": r[2],
                "user_id": r[3],
                "created_at": str(r[4]) if r[4] else None,
            }
            for r in rows
        ]

    async def get_mappings_for_user(
        self,
        user_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """All mappings for a specific user within a workspace."""
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("""
                    SELECT channel, channel_user_id, workspace_id,
                           user_id, created_at
                    FROM user_platform_mappings
                    WHERE user_id = :uid AND workspace_id = :ws
                    ORDER BY created_at DESC
                """),
                    {"uid": user_id, "ws": workspace_id},
                )
            ).fetchall()

        return [
            {
                "channel": r[0],
                "channel_user_id": r[1],
                "workspace_id": r[2],
                "user_id": r[3],
                "created_at": str(r[4]) if r[4] else None,
            }
            for r in rows
        ]

    async def update_mapping(
        self,
        channel: str,
        channel_user_id: str,
        workspace_id: str,
        new_user_id: str,
    ) -> bool:
        """Reassign a mapping to a different internal user."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    UPDATE user_platform_mappings
                    SET user_id = :new_uid
                    WHERE channel = :channel
                      AND channel_user_id = :cuid
                      AND workspace_id = :ws
                """),
                {
                    "new_uid": new_user_id,
                    "channel": channel,
                    "cuid": channel_user_id,
                    "ws": workspace_id,
                },
            )
        # Invalidate cache
        cache_key = (channel, channel_user_id, workspace_id)
        self._cache.pop(cache_key, None)
        return result.rowcount > 0

    async def delete_mapping(
        self,
        channel: str,
        channel_user_id: str,
        workspace_id: str,
    ) -> bool:
        """Remove a platform mapping."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                    DELETE FROM user_platform_mappings
                    WHERE channel = :channel
                      AND channel_user_id = :cuid
                      AND workspace_id = :ws
                """),
                {
                    "channel": channel,
                    "cuid": channel_user_id,
                    "ws": workspace_id,
                },
            )
        # Invalidate cache
        cache_key = (channel, channel_user_id, workspace_id)
        self._cache.pop(cache_key, None)
        return result.rowcount > 0
