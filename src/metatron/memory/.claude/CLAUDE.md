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
- `save(ws, record) -> MemoryRecord` — content dedup via exact-match hash, then PG → Qdrant → Neo4j (best-effort). Non-atomic. Before PG persistence, `record.content_simhash` is computed from `ingestion.dedup.simhash(content)` for near-duplicate health tracking (MTRNIX-277). On a dedup hit the existing record is returned immediately without recomputing the simhash on the rejected record.
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

### `health.py`
`MemoryHealthService` — compute per-agent memory health on demand (MTRNIX-277). Read-only; PG is the only backend consulted (Qdrant / Neo4j / Redis intentionally excluded).

Constructor: `MemoryHealthService(pg_store: MemoryPostgresStore, *, workspace_id: str, settings: Settings)`

Public method:
- `compute(agent_id: str) -> AgentMemoryHealth` — dispatch six independent aggregation queries via `asyncio.gather`, then compute duplicate clusters. Returns a frozen `AgentMemoryHealth` dataclass with:
  - `agent_id`, `total_records` (ACTIVE-only), `total_archived` (ARCHIVED + SUPERSEDED)
  - `growth_rate_per_day` (last-7-day ACTIVE creates / 7), `growth_timeseries` (30-day zero-filled `list[GrowthBucket]`, ascending)
  - `unused_records`, `unused_threshold_days` — records whose `last_accessed_at < cutoff OR (NULL AND created_at < cutoff)` within ACTIVE set
  - `duplicate_ratio` ∈ [0,1], `duplicate_clusters_count` (≥2-member clusters via union-find + hamming distance), `duplicate_hamming_threshold`
  - `duplicate_detection_skipped: bool`, `duplicate_active_population: int` — when ACTIVE count exceeds `_DUP_HARDCAP`, dup fields return `(0.0, 0)` and the `skipped` flag is `True` so the dashboard renders "Skipped — over Nk records" instead of misleading 0%
  - `source_distribution` (`dict[str, int]`, ACTIVE-only, zero counts omitted), `computed_at` (UTC ISO8601)

Implementation notes:
- Six independent PG aggregations fan out concurrently via `asyncio.gather`; avoids serialising pool acquisitions on the W9 polling dashboard.
- O(N²) SimHash hamming compare + union-find runs in `asyncio.to_thread` so the event loop stays responsive.
- `_DUP_HARDCAP = 5000` — when ACTIVE count exceeds this, duplicate fields return `(0.0, 0)`, the `duplicate_detection_skipped` flag flips to `True`, and a `memory_health.dup_skipped_size_cap` warn-log fires.
- NULL simhash rows (legacy records lacking a backfilled fingerprint) are skipped from cluster computation with a `memory_health.simhash_null_skipped` warn-log.
- No cache — recomputed on every call.

Helper types re-exported from `__init__.py`:
- `GrowthBucket(frozen dataclass)` — `day: date`, `created_count: int`
- `AgentMemoryHealth(frozen dataclass)` — the full snapshot described above

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

**Touch hook (MTRNIX-277):** after ranking, `hybrid_search` fires a `_safe_bulk_touch` task
that updates `last_accessed_at` for all returned record ids. The task is created via
`asyncio.create_task` and held in `self._touch_tasks: set[asyncio.Task[None]]` with a
`add_done_callback(set.discard)` so completed tasks are released automatically and the GC
cannot reap pending ones. `_safe_bulk_touch` swallows all exceptions with a warning log —
a PG failure on the touch path never fails a search response. The hook is skipped when
`agent_id is None`, `pg_store is None`, or the ranked list is empty. The hook fires on both
the REST `/api/v1/memory/search` and MCP `memory_search` paths because they share this service.

`MemorySearchWeights` — frozen dataclass (dense=0.6, graph=0.3, session=0.1, top_k_multiplier=3).

### `snapshot.py`
`MemorySnapshotService` — JSONL+gzip+SHA256 backup/restore for agent memory (MTRNIX-272, WS1 S4-5).
L3 service. PG is the source of truth; Qdrant and Neo4j are best-effort during restore.

Constructor: `MemorySnapshotService(pg_store, qdrant_store, workspace_id, snapshot_dir, *, max_file_bytes, event_bus?)`

Public methods:
- `create(agent_id, *, label, trigger) -> MemorySnapshot` — atomic write of gzip+sidecar (tmp+os.replace), calls `pg_store.save_snapshot`. 413-style `RuntimeError` on >10k records; `SnapshotCorruptError` on hash mismatch.
- `restore(snapshot_id) -> tuple[MemorySnapshot, int]` — returns `(pre_restore_snapshot, restored_count)`. SHA-256 verify → auto `pre_restore` snapshot → `pg_store.replace_for_agent` → best-effort Qdrant+Neo4j repopulation.
- `get(snapshot_id) -> MemorySnapshot` — fetch snapshot metadata from PG (404 → `MemoryNotFoundError`).
- `list_snapshots(agent_id) -> list[MemorySnapshot]` — newest-first listing from PG.
- `diff(from_id, to_id, *, key) -> SnapshotDiff` — compare two snapshots of the same agent. Cross-agent → `ValueError`.

File layout: `{snapshot_dir}/{workspace_id}/{agent_id}/{snapshot_id}.jsonl.gz` + sidecar `{snapshot_id}.sha256`.
Gzip body is self-describing: line 1 = JSON manifest (`version`, `snapshot_id`, `agent_id`, `workspace_id`, `record_count`, `created_at`); lines 2..N = serialised `MemoryRecord` JSON.

Helper types (also re-exported from `__init__.py`):
- `SnapshotTrigger(StrEnum)` — `manual | pre_reset | pre_restore`; written to `memory_snapshots.trigger`.
- `DiffKey(StrEnum)` — `source | content_hash`; controls which field is used as the diff key.
- `SnapshotDiff(dataclass)` — `from_snapshot_id, to_snapshot_id, key, added, removed, changed` (all id lists).

Key invariants:
- File writes are atomic (tmp file + `os.replace`) for both gzip and sidecar.
- `MemoryPostgresStore.replace_for_agent` runs in a single transaction (DELETE + INSERT).
- Qdrant/Neo4j failures on restore are logged at WARNING and never propagate — PG remains source of truth.
- Events emitted: `MEMORY_SNAPSHOT_CREATED` (`snapshot_id`, `trigger`, `record_count`) and `MEMORY_RESTORED` (`snapshot_id`, `record_count`, `pre_restore_snapshot_id`).

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
  `sync_downstream_stores(ws, target_id, *, status, freshness_score)` —
  MTRNIX-322: best-effort writes `{"status": status.value}` onto the
  per-workspace memory Qdrant point via `MemoryQdrantStore.update_payload`.
  Failures are logged at WARNING, counted on
  `freshness_qdrant_sync_failed_total{target_kind="memory_record",stage="sync_downstream"}`,
  and never propagate. PG remains source of truth; the backfill script at
  `scripts/backfill_memory_qdrant_status_payload.py` is the long-tail safety net.
  Callers: `FreshnessMonitor` (already wired in MTRNIX-313), `Curator`
  (MTRNIX-322), `apply_decision` mark_stale branch (MTRNIX-322).
  `list_stale_candidates(ws, *, older_than, limit)` — MTRNIX-316:
  delegates to `MemoryPostgresStore.list_stale_candidates` for the
  scheduled-scan safety net. Returns non-terminal rows older than
  `older_than`, ordered ASC by `updated_at`.
- `producer.py` — memory-side enqueue hook (unchanged signature).
- `worker.py` / `__main__.py` — worker entry point. Instantiates both a
  memory and (when `freshness_kb_enabled`) a KB pipeline and dispatches
  jobs by `target_kind`. **MTRNIX-316** adds per-worker processing-list
  reclaim + periodic scheduled scan: each worker claims a
  `worker_id = {hostname}:{pid}:{short-uuid}` at bootstrap, maintains
  `freshness:{env}:processing:{worker_id}` and `freshness:{env}:heartbeat:{worker_id}`,
  and every `METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS` iterations
  drains any orphaned peer's processing list back to the main queue via
  `reclaim_worker_orphans`. SIGKILL mid-batch no longer loses jobs.
  Scheduled scan (memory only in MTRNIX-316; KB deferred) enqueues
  synthetic `scheduled_scan` jobs for records that never received a
  write-triggered freshness event. Test-only env vars for the SIGKILL
  integration harness: `METATRON_FRESHNESS_TEST_WORKER_ID` (pins the
  worker id so key assertions are deterministic),
  `METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS` (widens the LMOVE → LREM
  window so the kill lands mid-batch). Do not set these in production.

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
`MemoryService`, `MemorySearchService`, `MemorySearchWeights`, `MemorySnapshotService`, `SnapshotDiff`, `SnapshotTrigger`, `DiffKey`, `MemoryHealthService`, `AgentMemoryHealth`, `GrowthBucket` — re-exported from `__init__.py`.
