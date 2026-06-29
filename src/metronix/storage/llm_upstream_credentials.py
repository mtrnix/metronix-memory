"""Async CRUD for llm_upstream_credentials (Fernet-encrypted upstream keys)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from sqlalchemy import text

from metronix.storage.encryption import decrypt_value, encrypt_value

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)


class LlmUpstreamCredentialsStore:
    """Stores Fernet-encrypted upstream API keys, workspace-scoped."""

    def __init__(self, engine: AsyncEngine, *, fernet_key: str) -> None:
        self._engine = engine
        self._fernet_key = fernet_key

    async def create(self, workspace_id: str, provider: str, plaintext_key: str) -> str:
        """Encrypt and store a key. Returns the new credential id."""
        cred_id = uuid4().hex
        encrypted = encrypt_value(plaintext_key, self._fernet_key)
        sql = text(
            """
            INSERT INTO llm_upstream_credentials
                (id, workspace_id, provider, fernet_encrypted_key)
            VALUES (:id, :ws, :provider, :enc)
            """
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                sql,
                {"id": cred_id, "ws": workspace_id, "provider": provider, "enc": encrypted},
            )
        return cred_id

    async def get_decrypted(self, cred_id: str, workspace_id: str) -> str | None:
        """Return the decrypted key, or None if not found in this workspace."""
        sql = text(
            """
            SELECT fernet_encrypted_key
            FROM llm_upstream_credentials
            WHERE id = :id AND workspace_id = :ws
            """
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"id": cred_id, "ws": workspace_id})
            row = result.first()
        if row is None:
            return None
        token = row[0]
        return decrypt_value(bytes(token), self._fernet_key)

    async def delete(self, cred_id: str, workspace_id: str) -> bool:
        """Delete a credential. Returns True if a row was removed."""
        sql = text("DELETE FROM llm_upstream_credentials WHERE id = :id AND workspace_id = :ws")
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, {"id": cred_id, "ws": workspace_id})
        return result.rowcount > 0
