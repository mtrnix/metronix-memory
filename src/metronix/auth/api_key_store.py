"""Personal API key store for OpenAI-compat endpoints.

Keys are random hex strings prefixed with 'mtk_'. The DB stores
SHA-256 hashes — a DB leak does not expose raw keys.

Table: api_keys (created lazily via ensure_schema)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)

KEY_PREFIX = "mtk_"
KEY_BYTES = 32


def _generate_raw_key() -> str:
    return f"{KEY_PREFIX}{secrets.token_hex(KEY_BYTES)}"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class ApiKeyStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._schema_ensured = False

    async def ensure_schema(self) -> None:
        async with self._engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id         TEXT PRIMARY KEY,
                        user_id    TEXT NOT NULL,
                        key_hash   TEXT NOT NULL UNIQUE,
                        key_prefix TEXT NOT NULL,
                        label      TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                )
            else:
                await conn.execute(
                    text("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id         TEXT PRIMARY KEY,
                        user_id    TEXT NOT NULL,
                        key_hash   TEXT NOT NULL UNIQUE,
                        key_prefix TEXT NOT NULL,
                        label      TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
                )
        self._schema_ensured = True
        logger.info("api_key_store.schema.ensured")

    async def _ensure(self) -> None:
        if not self._schema_ensured:
            await self.ensure_schema()

    async def create_key(self, user_id: str, label: str = "") -> str:
        """Create a new API key. Returns the raw key (shown once)."""
        await self._ensure()
        raw_key = _generate_raw_key()
        key_hash = _hash_key(raw_key)
        key_id = secrets.token_hex(16)
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                INSERT INTO api_keys (id, user_id, key_hash, key_prefix, label)
                VALUES (:id, :user_id, :key_hash, :key_prefix, :label)
            """),
                {
                    "id": key_id,
                    "user_id": user_id,
                    "key_hash": key_hash,
                    "key_prefix": raw_key[:12],
                    "label": label,
                },
            )
        logger.info("api_key.created", user_id=user_id, prefix=raw_key[:12])
        return raw_key

    async def resolve_key(self, raw_key: str, static_key: str = "") -> dict[str, Any] | None:
        """Resolve a raw API key to user info. Returns None if invalid."""
        if static_key and hmac.compare_digest(raw_key, static_key):
            return {"user_id": "openai-default", "source": "static"}

        await self._ensure()
        key_hash = _hash_key(raw_key)
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("""
                SELECT user_id, key_prefix, label, created_at
                FROM api_keys WHERE key_hash = :key_hash
            """),
                    {"key_hash": key_hash},
                )
            ).first()
        if row is None:
            return None
        return {
            "user_id": row[0],
            "key_prefix": row[1],
            "label": row[2],
            "created_at": row[3],
            "source": "personal",
        }

    async def list_keys(self, user_id: str) -> list[dict[str, Any]]:
        """List all keys for a user (without hashes)."""
        await self._ensure()
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("""
                SELECT id, key_prefix, label, created_at
                FROM api_keys WHERE user_id = :user_id
                ORDER BY created_at
            """),
                {"user_id": user_id},
            )
            return [
                {"id": r[0], "key_prefix": r[1], "label": r[2], "created_at": r[3]} for r in rows
            ]

    async def revoke_key(self, key_prefix: str, user_id: str) -> bool:
        """Revoke a key by its prefix. Returns True if deleted."""
        await self._ensure()
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""
                DELETE FROM api_keys
                WHERE key_prefix = :prefix AND user_id = :user_id
            """),
                {"prefix": key_prefix, "user_id": user_id},
            )
            return result.rowcount > 0
