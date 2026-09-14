"""Recover a connection after a credential/config change (#466).

``PostgresStore.update_connection`` only writes name/enabled/config. A
stale ``status='error'`` and an incremental ``last_synced_at`` cursor then
survive a credential fix, so the UI still shows the source as broken and
the next sync skips documents the old credentials could not see.

This module wraps ``PostgresStore.update_connection`` so a ``config``
change also sets ``status='active'``, ``error_message=NULL``, and
``last_synced_at=NULL`` — matching a successful ``POST .../test/`` (#463).
Name-only and enabled-only updates are left alone.

Installed from :mod:`metronix.storage.factory` so every production
constructor (API, MCP, CLI) gets the behaviour.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from metronix.storage.postgres import PostgresStore

_INSTALLED = False


async def recover_after_config_change(store: Any, connection_id: str, fernet_key: str) -> dict:
    """Clear error status and reset the incremental cursor for ``connection_id``."""
    async with store._engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE connections "
                "SET status = 'active', error_message = NULL, "
                "last_synced_at = NULL WHERE id = :id"
            ),
            {"id": connection_id},
        )
    return await store.get_connection(connection_id, fernet_key)


def install() -> None:
    """Wrap ``PostgresStore.update_connection`` once (idempotent)."""
    global _INSTALLED
    if _INSTALLED:
        return

    orig = PostgresStore.update_connection

    async def update_connection(
        self: PostgresStore, connection_id: str, updates: dict, fernet_key: str
    ) -> dict | None:
        result = await orig(self, connection_id, updates, fernet_key)
        if result is None or "config" not in updates:
            return result
        return await recover_after_config_change(self, connection_id, fernet_key)

    PostgresStore.update_connection = update_connection  # type: ignore[method-assign]
    _INSTALLED = True


install()
