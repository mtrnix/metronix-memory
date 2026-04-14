# Memory

## Overview
L3 — service layer for agent memory operations. Sits next to `llm/`, `skills/`, `workspaces/`.
Memory records are stored across three backends (Qdrant content, Neo4j relationships, Redis
session cache); this module orchestrates read-paths over them.

## Files

### `search.py`
`MemorySearchService.hybrid_search(workspace_id, query, *, agent_id=None, scope=None, tags=None, session_id=None, top_k=5)` — combines three parallel legs via `asyncio.gather`:
- Qdrant vector search (content relevance)
- Neo4j graph traversal (relationship presence, when `agent_id` provided)
- Redis session cache (recent-session boost, when `session_id` provided)

Each leg is wrapped in a local typed `_safe_gather_leg` helper so one backend down does
not fail search. Scores are min-max normalized (dense) then blended with weights from
`MemorySearchWeights`. Dedup by `record.id`, in-process tags filter, sort+rank+truncate.

`MemorySearchWeights` — frozen dataclass (dense=0.6, graph=0.3, session=0.1, top_k_multiplier=3).

Orchestration logic for save/promote/session lives in `agent/memory_service.py` (sibling task).
`agent/memory_service.py` has an optional `search: MemorySearchService | None` kwarg and a
thin `async def search(...)` delegate.

## Layer Rules
- Can import from: `core/` (L0), `storage/` (L1), `retrieval/` (L2).
- Must NOT import from: `agent/`, `channels/`, `api/`.

## Key Decisions
- **Weighted blend over RRF** — legs emit heterogeneous signals (relevance vs presence vs
  session recency). RRF assumes comparable rankings; blend lets us tune each signal's weight.
- **Graceful degradation via `_safe_gather_leg`** — one backend down does not fail search;
  the leg returns empty and the blend proceeds over the remaining signals.
- **Graph-only hits are dropped** — a MemoryRecord present only in Neo4j (no content in
  Qdrant) is skipped rather than emitted without text.
- **`sparse_score` field is reserved** — currently always 0.0; Qdrant fuses dense+sparse
  server-side via RRF. Field kept on `MemorySearchResult` for future client-side use.

## Public Surface
`MemorySearchService`, `MemorySearchWeights` — re-exported from `__init__.py`.
