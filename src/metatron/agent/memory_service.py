"""Backward-compatibility shim — MemoryService moved to metatron.memory.service.

Kept so enterprise plugins or external callers that still import from the old
path continue to work. New code should import from ``metatron.memory.service``.

Layer note: MemoryService is an L3 orchestration service over L1 storage
(PostgreSQL + Qdrant + Neo4j + Redis). Its canonical home is ``metatron.memory``.
"""

from __future__ import annotations

from metatron.memory.service import MemoryService

__all__ = ["MemoryService"]
