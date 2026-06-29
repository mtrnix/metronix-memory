"""L3 read-only service for KB raw_documents.

Layer: L3 (services) — same layer as ``memory/service.py``.
Imports only from L0 (core) and L1 (storage). No writes.

This module is the read-facade half of the unified knowledge endpoint
(Phase 1, memory-scopes). It deliberately does NOT:
- Write to raw_documents (that is the ingestion pipeline's job)
- Merge data with memory_records (the API route does that)
- Introduce an ``origin`` column (origin is endpoint-derived)
- Touch freshness lifecycle (that is the freshness worker's job)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from metronix.core.models import RawDocument
    from metronix.storage.postgres import PostgresStore

logger = structlog.get_logger(__name__)


class RawDocumentReadService:
    """Read-only access to ``raw_documents`` for a single workspace.

    Bound to ``workspace_id`` at construction (same idiom as
    :class:`~metronix.memory.service.MemoryService`) so the API layer cannot
    accidentally cross workspace boundaries.

    All reads fan out as a single ``asyncio.gather`` call — concurrency at
    zero extra complexity.
    """

    def __init__(
        self,
        pg_store: PostgresStore,
        *,
        workspace_id: str,
    ) -> None:
        self._pg = pg_store
        self._workspace_id = workspace_id

    async def list_records(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RawDocument], int]:
        """Return ``(records, total)`` for the bound workspace.

        Both ``list_raw_documents`` and ``count_raw_documents`` run
        concurrently via :func:`asyncio.gather`.  ``total`` is the
        workspace-wide count (not just the current page), enabling
        correct ``has_more`` computation.

        Args:
            limit: Page size, forwarded to
                :meth:`~metronix.storage.postgres.PostgresStore.list_raw_documents`.
            offset: Zero-based page offset.

        Returns:
            Tuple of (page records, total workspace record count).
        """
        logger.debug(
            "knowledge.raw_document_read_service.list",
            workspace_id=self._workspace_id,
            limit=limit,
            offset=offset,
        )
        records, total = await asyncio.gather(
            self._pg.list_raw_documents(
                self._workspace_id,
                limit=limit,
                offset=offset,
            ),
            self._pg.count_raw_documents(self._workspace_id),
        )
        return records, total
