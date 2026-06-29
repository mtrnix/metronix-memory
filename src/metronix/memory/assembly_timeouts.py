"""Per-stage timeouts for the AgentContextAssembler (MTRNIX-372)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metronix.core.config import Settings


@dataclass(frozen=True)
class AssemblyTimeouts:
    query_rewrite_ms: int = 400
    memories_ms: int = 800
    knowledge_ms: int = 800

    @classmethod
    def from_settings(cls, settings: Settings) -> AssemblyTimeouts:
        return cls(
            query_rewrite_ms=settings.proxy_query_rewrite_timeout_ms,
            memories_ms=settings.proxy_memory_search_timeout_ms,
            knowledge_ms=settings.proxy_knowledge_search_timeout_ms,
        )

    @property
    def query_rewrite_s(self) -> float:
        return self.query_rewrite_ms / 1000

    @property
    def memories_s(self) -> float:
        return self.memories_ms / 1000

    @property
    def knowledge_s(self) -> float:
        return self.knowledge_ms / 1000
