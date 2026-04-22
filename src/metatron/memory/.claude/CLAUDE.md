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
- `search(ws, query, agent_id?, scope?, tags?, session_id?, top_k?, status_filter?) -> list[MemorySearchResult]` — delegates to MemorySearchService
- `list_review_entries(ws, *, record_id?, reason?, limit?, offset?) -> (list[ReviewEntry], int)` — paginated list of review-queue rows for `target_kind=memory_record` (MTRNIX-314). Requires `freshness_store` kwarg at construction; raises `RuntimeError` otherwise.
- `resolve_review(ws, *, review_id, action, notes?, actor?) -> ReviewResolution` — apply `keep | archive | merge_into:<id> | discard` to a review entry (MTRNIX-314). Soft-transitions only; updates `memory_records.status`, deletes the review row, appends a `machine_events` row, best-effort Qdrant payload sync and `FRESHNESS_REVIEW_RESOLVED` EventBus emit.

Constructor kwargs:
- `search: MemorySearchService | None` — for the `search()` delegate.
- `freshness_store: FreshnessStore | None` (MTRNIX-314) — wires the review methods.
- `event_bus: EventBus | None` (MTRNIX-314) — when wired, `resolve_review` fires `FRESHNESS_REVIEW_RESOLVED`.

**Shim at `agent/memory_service.py`** — re-exports `MemoryService` from this module for
backward compatibility with older imports (e.g. enterprise plugins). New code should import
from `metatron.memory.service`.

### `search.py`
`MemorySearchService.hybrid_search(workspace_id, query, *, agent_id=None, scope=None, tags=None, session_id=None, top_k=5, status_filter=None)` — combines three parallel legs via `asyncio.gather`:
- Qdrant vector search (content relevance) — receives the computed `status_exclude`
  set so the filter pushes down to the payload (MTRNIX-314).
- Neo4j graph traversal (relationship presence, when `agent_id` provided)
- Redis session cache (recent-session boost, when `session_id` provided)

Each leg is wrapped in a local typed `_safe_gather_leg` helper so one backend down does
not fail search. Scores are min-max normalized (dense) then blended with weights from
`MemorySearchWeights`. Dedup by `record.id`, in-process tags filter, sort+rank+truncate.

Graph-only hits (no Qdrant peer, not in session cache) are status-filtered via a
batched `pg_store.get_many_statuses` lookup after leg fan-in (MTRNIX-314). Session
cache records are implicitly ACTIVE by construction (TTL semantics) and are never
filtered out by status. Constructor gains an optional `pg_store: MemoryPostgresStore | None`
kwarg — when None, the graph-leg post-filter is skipped (safe legacy default).

`MemorySearchWeights` — frozen dataclass (dense=0.6, graph=0.3, session=0.1, top_k_multiplier=3).

### `freshness/` — MTRNIX-304 Phase A

Background lifecycle maintenance for agent memory records. Feature-flagged via
`METATRON_FRESHNESS_ENABLED` (default `false`). Standalone worker process
launched via `python -m metatron.memory.freshness`.

Files:
- `coordination.py` — per-workspace Redis queue keys + Lua-scripted distributed locks.
- `producer.py` — `enqueue_if_enabled()` hook called by `MemoryService` after save/update/delete (no-op when flag off).
- `linker.py`, `reconciler.py`, `monitor.py`, `curator.py` — 5-stage pipeline (plus `decision_engine.py`).
- `decision_engine.py` — `DecisionEngine` Protocol, rule-based fallback, LLM-backed via `llm/provider.py`.
- `worker.py` / `__main__.py` — bounded-loop entry point, exponential backoff, heartbeat.
- `metrics.py` — optional Prometheus counters gated behind `try/except ImportError`.

Writes to `memory_records` lifecycle fields + `review_entries` + `machine_events`
via `storage/memory_postgres.py` (extended) and `storage/memory_freshness_pg.py`
(new). Each stage is idempotent — locks prevent races; re-runs converge.

**MTRNIX-313 (Phase B) relocation.** The shared stage code — `coordination.py`,
`decision_engine.py`, `apply_decision.py`, `metrics.py`, `stages/` (Linker,
Reconciler, FreshnessMonitor, Curator), and the `FreshnessTarget` protocol in
`targets.py` — has been promoted to `metatron.freshness.*` and is now generic
over the target kind. This subtree keeps only the memory-specific glue:
- `target_memory.py` — `MemoryTarget` adapter binding the pipeline to
  `MemoryPostgresStore` + `MemoryQdrantStore` + `memory_graph` + `RedisSessionCache`.
- `producer.py` — memory-side enqueue hook (unchanged signature).
- `worker.py` / `__main__.py` — worker entry point; now instantiates both a
  memory and (when `freshness_kb_enabled`) a KB pipeline and dispatches jobs
  by `target_kind`.

The module's sibling files (`linker.py`, `reconciler.py`, `monitor.py`,
`curator.py`, `coordination.py`, `decision_engine.py`, `metrics.py`) are now
thin re-export shims for backward compatibility; import from
`metatron.freshness.*` in new code.

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
