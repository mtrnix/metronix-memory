# Memory

## Overview
L3 — service layer for agent memory operations. Sits next to `llm/`, `skills/`, `workspaces/`.
Memory records are stored across four backends (PostgreSQL source-of-truth, Qdrant content,
Neo4j relationships, Redis session cache); this module orchestrates reads and writes over them.

## Files

### `service.py`
`MemoryService` — orchestrates writes across PG, Qdrant, Neo4j, Redis.
Bound to a single `workspace_id` at construction. All public methods assert
`workspace_id` matches the bound value.

Session methods (Redis + Neo4j write-through):
- `cache_session(ws, session_id, record, ttl?) -> MemoryRecord` — Redis primary, Neo4j best-effort
- `get_session(ws, session_id, record_id) -> MemoryRecord | None` — Redis first, PG fallback
- `list_session(ws, session_id) -> list[MemoryRecord]`
- `invalidate_session(ws, session_id) -> int`
- `extend_session_ttl(ws, session_id, ttl) -> bool`

Persistent methods (PG + Qdrant + Neo4j):
- `save(ws, record) -> MemoryRecord` — content dedup via exact-match hash, then PG → Qdrant → Neo4j (best-effort). Non-atomic.
- `get(ws, record_id) -> MemoryRecord | None` — PG (source of truth)
- `delete(ws, record_id) -> bool` — PG → Qdrant → Neo4j (best-effort)
- `list_records(ws, agent_id?, scope?, limit?, offset?) -> list[MemoryRecord]` — PG with filters
- `reset(ws, agent_id?, scope?) -> int` — DELETE RETURNING id from PG + per-id Qdrant + Neo4j cleanup
- `promote(ws, session_id, record_id, target_scope?) -> MemoryRecord` — Redis/PG → save to all stores; dedup-aware scope upgrade
- `search(ws, query, agent_id?, scope?, tags?, session_id?, top_k?) -> list[MemorySearchResult]` — delegates to MemorySearchService

Takes an optional `search: MemorySearchService | None` kwarg for the `search()` delegate.

**Shim at `agent/memory_service.py`** — re-exports `MemoryService` from this module for
backward compatibility with older imports (e.g. enterprise plugins). New code should import
from `metatron.memory.service`.

### `search.py`
`MemorySearchService.hybrid_search(workspace_id, query, *, agent_id=None, scope=None, tags=None, session_id=None, top_k=5)` — combines three parallel legs via `asyncio.gather`:
- Qdrant vector search (content relevance)
- Neo4j graph traversal (relationship presence, when `agent_id` provided)
- Redis session cache (recent-session boost, when `session_id` provided)

Each leg is wrapped in a local typed `_safe_gather_leg` helper so one backend down does
not fail search. Scores are min-max normalized (dense) then blended with weights from
`MemorySearchWeights`. Dedup by `record.id`, in-process tags filter, sort+rank+truncate.

`MemorySearchWeights` — frozen dataclass (dense=0.6, graph=0.3, session=0.1, top_k_multiplier=3).

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
  server-side via RRF. Field kept on `MemorySearchResult` for future client-side use
  (e.g. an MCP-layer `session_boost` signal — see `mcp/tools/memory_search.py`).

## Public Surface
`MemoryService`, `MemorySearchService`, `MemorySearchWeights` — re-exported from `__init__.py`.
