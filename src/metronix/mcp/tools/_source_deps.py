"""PostgresStore + Fernet acquisition for MCP source-management tools.

MCP tools run outside the FastAPI request scope (notably standalone
``python -m metronix.mcp``), so they cannot read ``app.state.postgres`` or the
Fernet key off a request. This mirrors ``_memory_deps`` with a process-level
cached store.

Underscore prefix intentional — internal to ``mcp/tools``.
"""

from __future__ import annotations

from metronix.core.config import get_settings
from metronix.storage.postgres import PostgresStore

_STORE: PostgresStore | None = None


def get_store() -> PostgresStore:
    """Return the process-cached PostgresStore (creating it on first use).

    Unlike :func:`resolve`, this does NOT require a Fernet key — it is for MCP
    tools that touch PostgreSQL but not encrypted connector credentials (e.g.
    ``metronix_store``). Sharing the singleton avoids spinning up a fresh async
    engine / connection pool on every call.
    """
    global _STORE
    if _STORE is None:
        _STORE = PostgresStore(get_settings().postgres_dsn)
    return _STORE


def resolve(workspace_id: str | None) -> tuple[str, PostgresStore, str]:
    """Return ``(workspace_id, store, fernet_key)`` for a source tool call.

    ``workspace_id`` falls back to the literal ``"default"`` to match every
    sibling MCP tool (NOT ``settings.default_workspace_id``, which resolves to
    ``"MTRNIX"`` and would split-brain with metronix_search/status). Raises
    ``ValueError`` when the Fernet key is unset.
    """
    ws_id = workspace_id or "default"
    store = get_store()
    key = get_settings().fernet_key
    if not key:
        raise ValueError("FERNET_KEY not configured. Set the FERNET_KEY env var.")
    return ws_id, store, key


def _reset_cache_for_tests() -> None:
    """Clear the cached store. Intended for unit tests only."""
    global _STORE
    _STORE = None
