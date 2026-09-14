"""Single construction point for the relational stores.

Phase 0 of the storage-layer extraction (see ``docs/STORAGE.md``). Every call
site that used to do ``PostgresStore(dsn)`` or ``MemoryPostgresStore(engine)``
now goes through :func:`build_document_store` / :func:`build_memory_store`, so a
future lightweight (single-user) edition can register a second backend in
exactly one place instead of chasing constructor calls across the codebase.

Today ``postgres`` is the only supported backend and the behaviour here is
byte-identical to calling the concrete constructors directly — this module adds
a seam, not a feature. ``STORAGE_BACKEND`` is validated at config load
(:class:`~metronix.core.config.Settings`) and re-checked here so the invariant
is also enforced at the storage seam itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metronix.core.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from metronix.storage.memory_postgres import MemoryPostgresStore
    from metronix.storage.postgres import PostgresStore

#: Relational backends this build can construct. A future edition adds ``"sqlite"``.
SUPPORTED_BACKENDS = frozenset({"postgres"})


def require_supported_backend() -> str:
    """Return the configured ``STORAGE_BACKEND``, or raise if this build lacks it.

    Defensive re-check of the same invariant ``Settings`` validates at load —
    keeps the failure legible and located at the storage seam if a caller
    constructs ``Settings`` some other way, or the config validator is later
    relaxed ahead of a backend actually being wired.
    """
    backend = get_settings().storage_backend
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"STORAGE_BACKEND={backend!r} is not supported by this build "
            f"(supported: {sorted(SUPPORTED_BACKENDS)}). "
            "See docs/STORAGE.md for the edition-split roadmap."
        )
    return backend


def build_document_store(dsn: str) -> PostgresStore:
    """Construct the document / connection / sync-log store.

    Backs ``raw_documents``, ``connections``, ``sync_logs``, ``connector_state``
    and the trace tables. For the ``postgres`` backend this mirrors
    ``PostgresStore(dsn)`` exactly — the store still creates and owns its own
    engine.
    """
    require_supported_backend()
    from metronix.storage.postgres import PostgresStore

    return PostgresStore(dsn)


def build_memory_store(engine: AsyncEngine) -> MemoryPostgresStore:
    """Construct the agent-memory record store on a caller-owned engine.

    Backs ``memory_records``, ``review_entries`` and the dedup-fingerprint
    helpers. For the ``postgres`` backend this mirrors
    ``MemoryPostgresStore(engine)`` exactly. Engine creation and caching stay
    with the caller in Phase 0; a later phase moves the connection lifecycle
    behind the factory.
    """
    require_supported_backend()
    from metronix.storage.memory_postgres import MemoryPostgresStore

    return MemoryPostgresStore(engine)
