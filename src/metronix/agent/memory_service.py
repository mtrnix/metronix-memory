"""Backward-compatibility shim — MemoryService moved to metronix.memory.service.

Kept so enterprise plugins or external callers that still import from the old
path continue to work. New code should import from ``metronix.memory.service``.

Layer note: MemoryService is an L3 orchestration service over L1 storage
(PostgreSQL + Qdrant + Neo4j + Redis). Its canonical home is ``metronix.memory``.
"""

from __future__ import annotations

from metronix.memory.service import MemoryService

__all__ = ["MemoryService"]
