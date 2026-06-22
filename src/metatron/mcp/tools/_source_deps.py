"""PostgresStore + Fernet acquisition for MCP source-management tools.

MCP tools run outside the FastAPI request scope (notably standalone
``python -m metatron.mcp``), so they cannot read ``app.state.postgres`` or the
Fernet key off a request. This mirrors ``_memory_deps`` with a process-level
cached store.

Underscore prefix intentional — internal to ``mcp/tools``.
"""

from __future__ import annotations

from metatron.core.config import get_settings
from metatron.storage.postgres import PostgresStore

_STORE: PostgresStore | None = None


def resolve(workspace_id: str | None) -> tuple[str, PostgresStore, str]:
    """Return ``(workspace_id, store, fernet_key)`` for a source tool call.

    ``workspace_id`` falls back to the literal ``"default"`` to match every
    sibling MCP tool (NOT ``settings.default_workspace_id``, which resolves to
    ``"MTRNIX"`` and would split-brain with metatron_search/status). Raises
    ``ValueError`` when the Fernet key is unset.
    """
    global _STORE

    settings = get_settings()
    ws_id = workspace_id or "default"
    if _STORE is None:
        _STORE = PostgresStore(settings.postgres_dsn)
    key = settings.fernet_key
    if not key:
        raise ValueError("FERNET_KEY not configured. Set the FERNET_KEY env var.")
    return ws_id, _STORE, key


def _reset_cache_for_tests() -> None:
    """Clear the cached store. Intended for unit tests only."""
    global _STORE
    _STORE = None
