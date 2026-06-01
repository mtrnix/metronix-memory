"""WorkspaceEntityTrie — lazy per-workspace entity matcher (MTRNIX-372).

Day-1: case-folded substring set lookup behind .match(). In-process LRU per
workspace with TTL + explicit invalidate(). Build via injected fetch_entities
(Neo4j Entity(workspace_id) scan), so storage stays decoupled.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Awaitable, Callable

import structlog

if TYPE_CHECKING:
    from metatron.core.config import Settings

logger = structlog.get_logger(__name__)

_MAX_WORKSPACES = 8


class WorkspaceEntityTrie:
    def __init__(
        self,
        *,
        settings: Settings,
        fetch_entities: Callable[[str], Awaitable[list[str]]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._fetch = fetch_entities
        self._clock = clock
        # workspace_id -> (lower_name -> original_name, built_at)
        self._cache: OrderedDict[str, tuple[dict[str, str], float]] = OrderedDict()

    def invalidate(self, workspace_id: str) -> None:
        self._cache.pop(workspace_id, None)

    async def _get_index(self, workspace_id: str) -> dict[str, str]:
        ttl = self._settings.proxy_entity_trie_ttl_seconds
        now = self._clock()
        cached = self._cache.get(workspace_id)
        if cached is not None and (now - cached[1]) < ttl:
            self._cache.move_to_end(workspace_id)
            return cached[0]
        names = await self._fetch(workspace_id)
        cap = self._settings.proxy_entity_trie_max_entities_per_ws
        index = {n.lower(): n for n in names[:cap] if n}
        self._cache[workspace_id] = (index, now)
        self._cache.move_to_end(workspace_id)
        while len(self._cache) > _MAX_WORKSPACES:
            self._cache.popitem(last=False)
        return index

    async def match(self, text: str, workspace_id: str) -> list[str]:
        index = await self._get_index(workspace_id)
        if not index:
            return []
        haystack = text.lower()
        return [original for lower, original in index.items() if lower in haystack]
