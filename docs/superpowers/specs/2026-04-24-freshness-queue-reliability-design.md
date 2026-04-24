# Freshness queue reliability — processing-list reclaim + scheduled scan — Design

**Date:** 2026-04-24
**Jira:** MTRNIX-316 — Freshness queue reliability — processing-list reclaim + scheduled scan (pre-prod gate).
**Depends on:** MTRNIX-304 (Phase A — merged), MTRNIX-313 (Phase B shared pipeline + `FreshnessTarget` protocol — merged), MTRNIX-322 (Qdrant status sync — merged).
**Parent ticket / context:** MTRNIX-304 spec, `docs/superpowers/specs/2026-04-20-freshness-worker-agent-memory-design.md` §"Known limitations — pre-prod hardening".
**Epic:** MTRNIX-227 (Agent Memory System, WS1).
**Author:** Architect (agent-team)
**Status:** Draft — ready for implementation plan

## Goal

Close the two pre-prod gaps that block flipping `METATRON_FRESHNESS_ENABLED=true`
in a production environment:

1. **Lossy dequeue on crash.** Today `CoordinationStore.dequeue_batch()` pops
   up to `max_items` jobs from `freshness:queue:{workspace_id}` via an atomic
   Lua `RPOP`×N. If the worker is SIGKILLed (OOM, container eviction, etc.)
   after popping N but before processing them, those jobs are lost. This
   makes Phase A under-process on transient failures — acceptable while
   the flag is off, not acceptable in production.
2. **Dev-rig key collisions.** `list_active_workspaces()` does
   `SCAN freshness:queue:*` with no environment tag. When multiple dev
   environments share a single Redis instance, a worker surfaces workspace
   ids from the wrong rig. Prod is unaffected (per-env Redis), but the hole
   is in the key schema, and fixing it before prod means fewer ops surprises.

Also deliver a scheduled-scan safety net so records that never receive a
write-triggered job (low-traffic workspaces, producer bugs, forgotten
imports) still get demoted to `STALE` eventually.

The fix is infra-only: Redis key layout, new per-worker Redis list, new
coordination methods, one new worker background task, one new producer-side
scan task. No PG schema change. No `core/interfaces.py` change. No
`core/events.py` change. No retrieval/MCP/API change. Worker started without
an env prefix still works (backwards-compatible default).

## Non-goals

- **KB scheduled scan.** `raw_documents.last_freshness_run_at` exists
  (migration 018) and the same scan shape would apply, but the memory side
  has no `last_freshness_run_at` column and the producer surface differs.
  This ticket scopes scheduled scan to memory only; KB scheduled scan is a
  follow-up for MTRNIX-313 owners (note in `docs/MEMORY_MCP_FOLLOWUPS.md`).
- **Cross-worker job stealing / work-stealing queue.** A worker never takes
  jobs from another live worker's processing list — only from lists whose
  owner has stopped heartbeating. Work-stealing is out of scope.
- **Global Redis lock on reclaim.** Reclaim uses atomic `LMOVE` per item;
  no outer lock is taken. Two workers trying to reclaim the same orphan
  simultaneously is resolved by `LMOVE`'s atomicity (only one wins per item).
- **Exactly-once delivery.** PG status updates remain idempotent (MTRNIX-304
  design invariant). Reclaim may cause a job to be processed twice; the
  pipeline's existing idempotency carries the load. We document the
  at-least-once delivery guarantee, we do not add dedup on record-id.
- **Key migration tooling.** When env-prefixed keys land, the old
  unprefixed keys (if any) are drained opportunistically at worker startup.
  No separate migration script. Rationale: the new worker is the only
  consumer; old unprefixed queues empty in one poll cycle. See §
  "Key migration" below.
- **Worker-process supervisor / autorestart.** Deployment concern. Docker /
  k8s restarts the worker; we only guarantee the queue survives that event.
- **New Prometheus label dimensions for per-workspace reclaim rate.**
  Reclaim is an infra rescue event — one counter with `worker_id` label is
  sufficient. Per-workspace drill-down comes from log search, not metrics
  (cardinality cost).

## Constraints

- **Layer boundaries.** All new code sits at L1 (`storage/redis.py` —
  two new primitives), L2 (`freshness/coordination.py`,
  `freshness/scheduled_scan.py`, `freshness/worker.py`), or L3
  (`memory/freshness/target_memory.py` — scheduled-scan provider glue).
  No upward imports. No changes to `core/interfaces.py`, `core/events.py`,
  `core/models.py`. `FreshnessTarget` Protocol gains one optional method
  (with a default `None` return) — backwards-compatible.
- **Workspace isolation.** Processing lists are per-worker (global key
  shape `freshness:{env}:processing:{worker_id}`), but every serialised job
  inside still carries its `workspace_id`. Scheduled scan enumerates
  workspaces via the existing `postgres.list_workspaces` helper (already
  used by other background jobs) — never scans across tenants by Redis key
  alone.
- **Graceful degradation.** Reclaim and scheduled-scan failures log WARNING
  + increment a counter, never abort the worker loop. Matches the
  MTRNIX-322 swallow-pattern.
- **Backwards compatibility.** `METATRON_ENV` is already validated to
  `{development, staging, production}`. When the setting is unset in
  legacy local-dev rigs, the env prefix defaults to `""` and the key shape
  stays byte-identical to Phase A (`freshness:queue:{workspace_id}`).
- **Best-effort semantics.** Reclaim loss (Redis down during `LMOVE`, worker
  crash during reclaim) reduces to the existing PG-source-of-truth + scan
  safety net. We tolerate it.
- **At-least-once delivery.** A reclaimed job may run twice. Pipeline
  stages are idempotent by design (MTRNIX-304 invariant); the DecisionEngine
  rule-based engine is stable for the same content; `apply_decision` is
  idempotent on status/tag writes; MachineEvent rows are append-only (two
  `freshness_job_processed` rows for a reclaimed job is acceptable and
  discoverable via the audit log).
- **No new pg indexes.** Scheduled scan reads `memory_records` ordered by
  `updated_at` with a bounded limit. The existing
  `idx_memory_records_workspace` + `updated_at` sort is sufficient for the
  scan's workspace-scoped window (bounded by
  `METATRON_FRESHNESS_SCAN_BATCH_LIMIT`, default 500).

## Current state — what needs changing

Current `CoordinationStore` (`src/metatron/freshness/coordination.py`):

- Queue key:        `freshness:queue:{workspace_id}` (unprefixed)
- Lock key:         `freshness:{stage}:{target_id}` (unprefixed)
- `dequeue_batch` → single atomic `rpop_batch` (Lua). Lossy on crash.
- `list_active_workspaces` → `SCAN freshness:queue:*` (unprefixed, collides
  across dev rigs).
- No processing list. No `worker_id`. No heartbeat key. No reclaim method.
- No scheduled-scan module.

Current `RedisStore` (`src/metatron/storage/redis.py`):

- Exposes: `lpush`, `rpop_batch`, `llen`, `scan_keys`, `acquire_lock`,
  `heartbeat_lock`, `release_lock`, `get/set/delete/exists/expire`.
- **Does NOT expose `LMOVE`, `BRPOPLPUSH`, `LREM`, or blocking-pop
  primitives.** This ticket adds the minimum needed (`lmove` + `lrem`).

Current `FreshnessWorker` (`src/metatron/memory/freshness/worker.py`):

- `run_once` iterates workspaces → `dequeue_batch` → process. No
  worker-id concept. No heartbeat tick. No reclaim pass. No scheduled-scan
  hook.
- `main()` wraps `_run_loop` with exponential backoff. Hard-exits after N
  consecutive errors.

Current `FreshnessTarget` Protocol (`src/metatron/freshness/targets.py`):

- Has `get`, `update_lifecycle`, `similarity_search`, `link_edges_batch`,
  `alias_edge`, `sync_downstream_stores`. No scan / enumerate method. We
  add one optional method (`list_stale_candidates`) with a default
  `return []` so KB's `RawDocumentTarget` keeps working untouched.

Current `Settings` (`src/metatron/core/config.py`):

- `env: str = Field("development", alias="METATRON_ENV")`, validated to
  `{development, staging, production}`. **This is the env-prefix source.**
  We do NOT add a new `METATRON_FRESHNESS_ENV` — reuse the canonical one.
- `freshness_*` flags: `freshness_enabled`, `freshness_poll_seconds`,
  `freshness_lock_ttl_seconds`, `freshness_stale_after_days`,
  `freshness_max_consecutive_errors`, etc. We add five new flags for the
  reliability features (§ "Config" below).

## Architecture

### 12 open questions — all closed

#### 1. `BRPOPLPUSH` vs `LMOVE`

**Decision: `LMOVE`.** Redis 6.2 (Feb 2021) made `BRPOPLPUSH` deprecated
and introduced `LMOVE` as the canonical primitive. Metatron's docker-compose
stack pins Redis to `redis:7-alpine` (verified in `docker-compose.yml`) and
the production image target is Redis 7.x, well above 6.2. The `LMOVE`
signature is:

```
LMOVE source destination (LEFT|RIGHT) (LEFT|RIGHT)
```

We use `LMOVE queue processing RIGHT LEFT` — take the oldest queued job
(RIGHT, FIFO) and push it to the head of the per-worker processing list
(LEFT). Non-blocking (we poll); when the queue is empty, `LMOVE` returns
nil and `dequeue_batch` just stops early.

The Lua `RPOP×N` atomic-batch primitive is abandoned. `dequeue_batch`
becomes a loop of up to N `LMOVE` calls. See § 6 for the perf trade-off.

Redis version requirement: **>= 6.2.0**. Documented in
`CHANGELOG.md` and `docker-compose.yml` comment.

#### 2. Worker identity

**Decision: composite `{hostname}:{pid}:{short-uuid}`, ephemeral
(not persisted to disk).**

Rationale:

- `hostname` is stable per container / pod / dev rig. Operators reading
  logs can eyeball "which machine".
- `pid` disambiguates multiple workers on the same host (dev rigs running
  two workers for smoke tests).
- `short-uuid` (first 8 hex of `uuid4().hex`) disambiguates restart after
  a crash so the *new* worker's processing list is empty and orphans from
  the old pid are discoverable by TTL-expired heartbeat (§ 3).

We deliberately do NOT persist `worker_id` to disk:

- Disk persistence complicates docker/k8s (volumes, paths, permissions).
- Goal is "orphan reclaim after crash," not "same worker picks up its own
  half-done batch." On crash, we want the orphan list to be visible to
  the reclaim pass under a dead worker's name.
- Persistence would also require a worker-side "resume my processing list"
  code path on startup — more surface area, same end result.

Helper: `src/metatron/freshness/worker_id.py` exposes
`build_worker_id() -> str`. Called once at worker bootstrap. The worker
stores it on `self._worker_id` and passes it through to every
coordination call.

`list_active_workspaces` today SCANs for `freshness:queue:*`. The reclaim
pass needs the analogous SCAN for `freshness:{env}:processing:*`. New
coordination method:
`list_processing_workers() -> list[str]` — strips prefix, returns worker
ids. See § 5.

#### 3. Heartbeat mechanism

**Decision: per-worker heartbeat key
`freshness:{env}:heartbeat:{worker_id}` with TTL = `2 × heartbeat_ttl`
(default `heartbeat_ttl = 10s`, so key TTL = 20s). Worker refreshes the
key at the start of every `run_once` iteration and after every job's
`_process_job` return.**

Rationale:

- TTL key semantics give O(1) "is this worker alive?" check:
  `EXISTS freshness:{env}:heartbeat:{worker_id}` → dead if missing.
- Two-iteration expiry tolerates a slow poll cycle without false-declaring
  a live worker dead. Default poll is 2s + up to 20 jobs processing; the
  20s budget is comfortable.
- No separate "heartbeat thread / coroutine" — refreshing on iteration
  boundaries is enough and avoids concurrency bugs. (Long-running single
  stages already have their own per-lock heartbeat via
  `CoordinationStore.heartbeat` — this is an orthogonal concern at the
  worker level.)
- Token-guarded `SET NX EX` lock primitives are not needed here — the
  heartbeat key is unique per worker and nobody else writes it; a plain
  `SET key worker_id EX ttl` (upsert, no NX) is correct.

New `CoordinationStore` methods:

- `async def tick_heartbeat(worker_id: str, ttl: int) -> None`
  — upsert-set the heartbeat key with TTL.
- `async def is_worker_alive(worker_id: str) -> bool`
  — `EXISTS` check; false on Redis failure (fail-closed; reclaim will
  retry next iteration).
- `async def release_worker(worker_id: str) -> None`
  — delete the heartbeat key on graceful shutdown (best-effort, doesn't
  matter if missed — TTL cleans up).

#### 4. Where reclaim runs

**Decision: inside the worker loop, every N iterations, gated by
`freshness_reclaim_interval_iterations` (default 30).**

Rationale:

- **Reject (a) startup-only.** A worker that never restarts (healthy
  prod) never reclaims. Orphans from a sibling crash stay orphaned
  indefinitely.
- **Reject (c) separate cron / new process.** Adds deployment complexity
  (separate container, separate env injection). The worker already runs
  an async loop; adding a periodic pass costs nothing.
- **Accept (b) worker-loop periodic.** Simple, guaranteed-running, ops-free.
  Every ~60s (default poll 2s × 30 iterations) each live worker scans for
  dead-worker processing lists and reclaims them. Two workers reclaiming
  the same orphan are safe — `LMOVE` on an empty list is a no-op.

Additional trigger: **worker startup also runs one reclaim pass
immediately** (before entering `_run_loop`). Rationale: in a single-worker
deployment, a restart after SIGKILL is the canonical recovery path; we
want the orphaned processing list drained immediately, not after the 30th
iteration.

Implementation: new coroutine `FreshnessWorker._reclaim_orphans()` called
from:

1. `_build_worker` (once, at startup, before `_run_loop`).
2. `run_once` (every `freshness_reclaim_interval_iterations` iterations —
   counter lives on `self`).

All reclaim work wrapped in `try/except Exception` — logged, counter
bumped, never raises.

#### 5. Atomic reclaim

**Decision: per-item `LMOVE source=processing dest=queue RIGHT LEFT`.**

Sequence, per dead worker:

1. Discover: `list_processing_workers` returns all `{worker_id}` with a
   non-empty processing list for the current env.
2. For each one: check `is_worker_alive(worker_id)`. If alive → skip.
3. Drain: repeat `LMOVE processing:{worker_id} queue:{workspace_id}
   RIGHT LEFT`. But the processing list holds serialised jobs for mixed
   workspaces — the destination queue depends on the job payload.

**Refinement.** The processing list holds `_serialize_job(job)` strings
(the exact same bytes the main queue holds). The LIFO-vs-FIFO direction
doesn't matter for correctness — all that matters is that each moved
item lands on the right workspace queue.

The naive per-item recipe:

```
raw = LRANGE processing:{worker_id} -1 -1    -- tail (oldest first in)
if raw is nil: done
job = deserialize(raw)
LMOVE processing:{worker_id} queue:{job.workspace_id} RIGHT LEFT
```

But `LMOVE` moves by position, not value. Between `LRANGE` and `LMOVE`
another reclaimer could remove that tail. So we use the standard
`RPOPLPUSH`-equivalent idiom **with poison recovery**: the job's
`workspace_id` is extracted on inspection; if `LMOVE` lands on the wrong
queue, we simply don't — we use the **value-aware** primitive pair:

```
raw = LINDEX processing:{worker_id} -1
if raw is nil: done
dst = queue_key_for(parse(raw).workspace_id)
moved = LMOVE processing:{worker_id} dst RIGHT LEFT
  -- moves current tail; if another reclaimer was faster, moves a different
  -- item to the wrong queue
```

The race between `LINDEX` + `LMOVE` on the same processing list is the
classic "concurrent reclaimers on same orphan" problem. We resolve it by
**serialising reclaim per worker_id with a short-TTL lock key**:

```
lock_key = freshness:{env}:reclaim_lock:{worker_id}
if not SET lock_key self NX EX 30: skip   -- another reclaimer has it
...drain...
DEL lock_key
```

Live workers reclaiming their own orphans is physically impossible (they
wouldn't be orphans). The lock just prevents two live workers from
stepping on each other while draining a dead peer. The lock's TTL (30s)
is a safety net — if the reclaimer itself crashes mid-drain, the next
iteration picks up where it left off.

**Dead-worker heartbeat race.** A "dead" worker might actually be a live
worker whose heartbeat key expired due to Redis latency. On reclaim we
`LMOVE` their processing-list tail back into the main queue. The live
worker then finishes processing and does `LREM processing ... value` —
the value no longer exists on the processing list, so `LREM` is a no-op.
The worker then `tick_heartbeat`s and is live again. Worst case: one job
ran twice. Covered by at-least-once delivery + idempotent stages. Logged
at INFO (`freshness.reclaim.race`) for observability; does not count as
an error.

New `CoordinationStore` methods:

- `async def list_processing_workers() -> list[str]` — SCAN
  `freshness:{env}:processing:*` and strip prefix.
- `async def processing_list_has_items(worker_id: str) -> bool` — `LLEN > 0`.
- `async def reclaim_worker_orphans(worker_id: str) -> int` — full drain
  flow above; returns count moved.

Lua glue for the per-item value-aware drain step sits in `RedisStore`
(L1) so coordination (L2) stays declarative:

- `async def lmove_rightleft(src: str, dst: str) -> str | None` — thin
  `LMOVE src dst RIGHT LEFT` wrapper; returns the moved value or None
  when the source was empty.
- `async def peek_tail(key: str) -> str | None` — `LINDEX key -1`.
- `async def lrem(key: str, value: str, count: int = 1) -> int` —
  `LREM key count value` (LREM wrapper; count=1 matches first from head).
- Keep existing `acquire_lock` / `release_lock` for the per-worker
  reclaim lock; the lock_key is a regular Redis key, no Lua changes.

#### 6. `dequeue_batch` no longer atomic — performance hit

**Accepted. Documented.** Today: 1 Lua round-trip pops up to 20 jobs.
After: 1..N `LMOVE` round-trips pop 1..N jobs.

Quantified:

- Default `freshness_max_jobs_per_iteration = 20` (Phase A).
- Redis round-trip on localhost: ~0.2-0.5ms. On docker-compose with a
  shared host: ~0.5-1.0ms. In prod (kube, separate pod): 1-2ms.
- 20 `LMOVE`s × 2ms = 40ms added latency per iteration.
- Iteration work dominates: Linker+Reconciler+Monitor+Curator +
  DecisionEngine + apply_decision runs hundreds of ms per job.
- Net impact: ~1% iteration overhead. Acceptable.

Alternative rejected: a Lua "atomic multi-LMOVE into processing list"
script. Lua gets us atomicity for free, but the values on the processing
list are heterogeneous workspace-id-wise — Lua cannot return "N values +
their target queue keys" cleanly, and partial-failure recovery adds
complexity equivalent to just doing N round-trips. The N-round-trip
version is also trivial to reason about; perf is in the noise.

Optional: when `freshness_max_jobs_per_iteration` is much higher (for
stress tests), pipelining the N `LMOVE`s via `redis.asyncio.Pipeline`
cuts RTT by ~30-40%. We add pipelining only if benchmarks show we need
it (not in scope for MTRNIX-316; `# TODO(perf)` comment).

#### 7. Scheduled-scan placement

**Decision: inside the worker loop (option a), gated by
`freshness_scheduled_scan_interval_seconds` (default 3600 — hourly).**

Rationale:

- **Reject (b) separate cron/process.** Deployment surface doubles
  (container, env config, secrets) for a task that runs once an hour for
  a few seconds. Not worth it.
- **Accept (a) in-loop.** Worker already runs continuously. Scan is
  bounded by `freshness_scan_batch_limit` (default 500 records per
  workspace per scan) — stable cost. Runs every ~1h, taking maybe 1-10s.
- Triggered by a simple monotonic timer on `self`: if `time.monotonic() -
  self._last_scan_monotonic > interval`, run scan. Early iterations skip
  cleanly.

Module layout:

- New: `src/metatron/freshness/scheduled_scan.py` — target-agnostic scan
  orchestrator. Takes a `FreshnessTarget`, a `CoordinationStore`, the
  `stale_after_days` config, and the `batch_limit`. Enumerates workspaces
  via injected `workspace_lister` callable (delegates to
  `PostgresStore.list_workspaces` — the existing helper already used by
  the sync-logs background task). For each workspace, asks the target
  for the stale-candidate IDs and enqueues `scheduled_scan` freshness
  jobs idempotently.
- Worker wiring: `FreshnessWorker` gains an optional
  `scheduled_scanners: list[ScheduledScan]` ctor kwarg (one per target
  kind). When `scheduled_scan_interval_seconds == 0` or the flag
  `freshness_scheduled_scan_enabled=False`, skip. Default
  `freshness_scheduled_scan_enabled=True` (safety net is on by default;
  it's a pure rescue path).

#### 8. Scheduled-scan scope

**Decision: memory only for this ticket. KB deferred.**

Rationale:

- The memory path has a clean enumeration: `MemoryPostgresStore.list_records`
  with `updated_at < now - stale_after_days` filter fits natively. Add a
  thin wrapper: `list_stale_candidates(workspace_id, older_than, limit)`
  → list of record_ids, ordered by `updated_at ASC`.
- The KB path already has `raw_documents.last_freshness_run_at` (migration
  018) — a different and richer signal. The "no `machine_events.
  freshness_job_processed` in the stale window" predicate from the ticket
  description is equivalent to `last_freshness_run_at IS NULL OR <
  now - window`. KB's scan predicate is therefore subtly different, and
  so is the idempotence protocol (producer enqueues with a dedup key
  based on `last_freshness_run_at` vs. memory's own per-record tracking).
- Shipping both in one ticket doubles the surface area and couples the
  rollout. Memory is the MTRNIX-316 AC gate; KB scheduled scan becomes
  MTRNIX-316-follow in `docs/MEMORY_MCP_FOLLOWUPS.md`. The shared
  `ScheduledScan` orchestrator designed here accepts any
  `FreshnessTarget` with `list_stale_candidates` → trivial extension
  when KB wants it.

`FreshnessTarget` Protocol — one new optional method with a default:

```python
async def list_stale_candidates(
    self,
    workspace_id: str,
    *,
    older_than: datetime,
    limit: int,
) -> list[str]:
    """Return up to ``limit`` target_ids older than ``older_than``.

    Default implementation returns an empty list. Targets opt in by
    overriding. Used by the scheduled-scan rescue path to enqueue jobs
    for records that never received a write-triggered freshness event.
    """
    return []
```

Memory adapter (`MemoryTarget`) overrides this method to delegate to
`MemoryPostgresStore.list_stale_candidates(workspace_id, older_than,
limit)` — a new method that adds a single parametrised SELECT. KB target
keeps the default (empty) implementation for now; the KB implementation
is a trivial follow-up.

#### 9. Env prefix source

**Decision: reuse `settings.env` (`METATRON_ENV`), no new variable.**

- The value is already validated to `{development, staging, production}`
  (see `Settings.validate_env`).
- Fallback for edge cases (unset / empty): treat as `""` and emit the
  Phase A unprefixed key shape — byte-identical to pre-MTRNIX-316
  behaviour. Rationale: legacy local-dev setups that source a minimal
  `.env` without `METATRON_ENV` keep working without a code change.
- Defining a new `METATRON_FRESHNESS_ENV` is explicitly rejected — see
  ticket guidance. One knob per concern.

Key shape helper:

```python
def _key_prefix() -> str:
    env = get_settings().env
    return f"freshness:{env}:" if env else "freshness:"
```

Applied consistently to queue, processing, heartbeat, and reclaim-lock
keys. Lock keys (`freshness:{stage}:{target_id}`) ALSO prefix the env in
the same way, for symmetry and to prevent dev-rig lock collisions.

#### 10. Key migration

**Decision: opportunistic drain at worker startup. No separate tool.**

When the new code ships:

- If `METATRON_ENV` was set to (say) `development` from day one, the
  unprefixed keys have never existed — nothing to migrate.
- If the env was unset before (local dev), the old unprefixed keys stay
  valid (env defaults to `""` → no prefix) and the worker consumes them
  normally.
- If the env gets flipped from unset to a value (dev rig adds `METATRON_
  ENV=development`), the unprefixed keys become stale. The worker's
  startup hook checks for both prefixed and unprefixed active workspace
  queues, drains any unprefixed work into the prefixed equivalents one
  time, and thereafter only reads prefixed keys.

Implementation: new startup helper
`CoordinationStore.drain_legacy_unprefixed() -> int`. Runs once in
`_build_worker` after the first reclaim pass. Best-effort — logs, counter
bump, never raises. Disabled by default when the env prefix is empty
(nothing to do). Safe to run repeatedly (idempotent — on the second run
the legacy keys are empty).

One log line per draining workspace; aggregate counter
`freshness_legacy_keys_drained_total{env}`. Off by default via gate
`freshness_drain_legacy_at_startup` — when ops opts-in during the
env-prefix rollout, flip the flag to true for one deploy cycle, then
remove from the env. Avoids an unexpected background SCAN on dev rigs
that pre-date the flag.

#### 11. Integration test

**Decision: subprocess-spawned worker + `os.kill(worker.pid,
signal.SIGKILL)` mid-batch. No asyncio cancellation.**

Rationale:

- `asyncio.Task.cancel()` injects `CancelledError` which the worker's
  try/finally catches cleanly — this is NOT what we're testing. We're
  testing SIGKILL semantics: process dies mid-batch with no chance to
  release locks, drain processing lists, or close connections.
- `subprocess.Popen([sys.executable, "-m",
  "metatron.memory.freshness"])` with the test `METATRON_*` env passed
  through gives a real process. Integration test orchestrates:

```
1. Seed workspace + N memory records + enqueue N jobs.
2. Spawn worker subprocess; wait for processing list to have >= M items
   (poll `LLEN freshness:{env}:processing:{worker_id}`).
3. os.kill(proc.pid, signal.SIGKILL); proc.wait(timeout=5).
4. Assert: queue + processing list combined still contains N jobs (none
   lost).
5. Start a second worker subprocess (different worker_id).
6. Wait for its reclaim pass; assert dead worker's processing list is
   drained and total N jobs end up processed.
7. Clean up both processes + PG state + Redis keys.
```

- Worker spawn is parameterised via a test helper
  `_spawn_worker(workspace_id, worker_id_override)`. `worker_id_override`
  is a test-only env var consumed by `build_worker_id` — lets the test
  pin the id so the reclaim assertion is deterministic.
- Kill point is chosen via a custom env-injected delay: worker picks up
  one job, sleeps (mocked via `METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS`)
  so the test has a deterministic window between "batch popped" and
  "batch processed" to fire SIGKILL.

Location:
`tests/integration/memory/freshness/test_reclaim_sigkill.py`.
`pytest.mark.integration`. Uses live PG + Redis + Qdrant (existing
integration fixture conventions).

Two additional integration tests:

- `test_scheduled_scan_enqueues_stale.py` — seed 3 records with
  `updated_at` past the threshold, run the scan once, assert jobs
  enqueued and processed.
- `test_env_prefix_isolation.py` — enqueue jobs under
  `METATRON_ENV=staging` key shape; start a worker with `development`;
  assert the worker ignores the staging queue entirely.

#### 12. Observability

**Decision: five new counters.** All follow the MTRNIX-322 pattern
(Prometheus guarded by `try/except ImportError`, noop stubs otherwise),
added to `src/metatron/freshness/metrics.py`.

| Counter | Labels | Meaning |
|---|---|---|
| `freshness_orphans_reclaimed_total` | `env`, `worker_id_hash` | Jobs moved from dead-worker processing list back to queue. `worker_id_hash` = first 4 hex of SHA1(worker_id) — bounded cardinality. |
| `freshness_reclaim_errors_total` | `env`, `stage` (`discover`, `drain`, `release`) | Reclaim pass failures. |
| `freshness_scheduled_scan_jobs_enqueued_total` | `env`, `target_kind` | Records enqueued by the scheduled-scan safety net. |
| `freshness_scheduled_scan_errors_total` | `env`, `target_kind` | Scan failures (PG or Redis). |
| `freshness_legacy_keys_drained_total` | `env` | Migration counter. |

Cardinality audit:

- `env` bounded to `{"", "development", "staging", "production"}` = 4.
- `worker_id_hash` bounded to 65536 (4 hex). In practice dev has ~1-2
  workers; prod has ~1-4. Fine.
- `target_kind` bounded to `{memory_record, raw_document}` = 2.
- `stage` bounded to 3.

Gauge (optional, nice-to-have):
`freshness_processing_list_depth{worker_id_hash, env}` — updated on the
reclaim pass. **Deferred.** Not in AC; a follow-up once reclaim rates
are observed.

Structured log events (structlog):

- `freshness.worker.worker_id_assigned` — once at boot (INFO).
- `freshness.worker.heartbeat_tick` — DEBUG (per iteration).
- `freshness.reclaim.start` — INFO (per reclaim pass).
- `freshness.reclaim.discovered` — INFO (workers found).
- `freshness.reclaim.dead_worker_detected` — WARNING (orphan found).
- `freshness.reclaim.jobs_recovered` — INFO (per dead worker, count).
- `freshness.reclaim.race` — INFO (unexpected `LREM` miss).
- `freshness.reclaim.failed` — WARNING (single-iteration failure).
- `freshness.scheduled_scan.start` — INFO.
- `freshness.scheduled_scan.enqueued` — INFO (per workspace, count).
- `freshness.scheduled_scan.failed` — WARNING.
- `freshness.legacy.drain.start` — INFO (once).
- `freshness.legacy.drain.done` — INFO (once, with count).

## Data flow — before vs after

### Dequeue path — before (today, lossy)

```
run_once:
  for ws in list_active_workspaces():
    jobs = dequeue_batch(ws, N)    # atomic RPOP x N
    for job in jobs:
      process(job)                  # if worker dies here → jobs gone
```

### Dequeue path — after

```
bootstrap:
  worker_id = build_worker_id()
  tick_heartbeat(worker_id)
  reclaim_orphans()                 # immediate one-shot

run_once (every iteration):
  tick_heartbeat(worker_id)
  if iteration % reclaim_interval == 0:
      reclaim_orphans()             # periodic
  if time_since_last_scan > scan_interval:
      scheduled_scan_run()          # safety net

  for ws in list_active_workspaces():
    jobs = dequeue_batch(ws, N, worker_id=worker_id)
      # under the hood: N loops of
      #   lmove_rightleft(queue, processing)
      # parse, collect, return
    for job in jobs:
      try:
        process(job)
      finally:
        lrem(processing, _serialize_job(job), count=1)
        # → job is removed from processing list whether we succeeded,
        #   failed, or raised. On raise, existing error path still bumps
        #   worker_errors counter and re-enqueues via retry logic (Phase A
        #   already has none beyond crash re-enqueue from reclaim — we do
        #   not add retry; stage-internal errors log + move on).
```

### Reclaim pass

```
reclaim_orphans:
  for worker_id in list_processing_workers():
    if is_worker_alive(worker_id):
      continue
    if not acquire_lock(reclaim_lock:{worker_id}, ttl=30):
      continue   # another reclaimer has it
    try:
      while True:
        raw = peek_tail(processing:{worker_id})
        if raw is None: break
        job = deserialize(raw)
        dst = queue_key_for(job.workspace_id)
        moved = lmove_rightleft(processing:{worker_id}, dst)
        if moved is None: break   # race, loop exits cleanly
        counter.inc(labels={"env": env, "worker_id_hash": hash(worker_id)})
    finally:
      release(reclaim_lock:{worker_id})
```

### Scheduled scan

```
scheduled_scan_run:
  for target_kind, scanner in self._scheduled_scanners.items():
    try:
      workspaces = await workspace_lister()   # PG helper
      older_than = now() - timedelta(days=stale_after_days)
      for ws in workspaces:
        ids = await scanner.target.list_stale_candidates(
            ws, older_than=older_than, limit=scan_batch_limit
        )
        for rid in ids:
          await coordination.enqueue_job(FreshnessJob(
              workspace_id=ws,
              event_type="scheduled_scan",
              target_kind=target_kind,
              target_id=rid,
              payload={"older_than_iso": older_than.isoformat()},
          ))
        if ids:
            metrics.scheduled_scan_jobs_enqueued.labels(
                env=env, target_kind=target_kind,
            ).inc(len(ids))
    except Exception:
      metrics.scheduled_scan_errors.labels(...).inc()
      logger.warning("freshness.scheduled_scan.failed", ...)
```

Scan idempotence: the pipeline already dedups by `freshness_job_received`
MachineEvent — re-enqueuing a record that's recently been processed just
produces another log row. In Phase B language this is "at-least-once
delivery, idempotent consumer."

## Config (new env vars, `METATRON_` prefix)

All default values chosen so that enabling env-prefix / scheduled-scan
is a no-op for pre-MTRNIX-316 dev rigs:

| Env var | Default | Type | Notes |
|---|---|---|---|
| `METATRON_FRESHNESS_HEARTBEAT_TTL_SECONDS` | `20` | int | 2× iteration poll budget. |
| `METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS` | `30` | int | Reclaim pass every ~60s (at default `poll_seconds=2`). |
| `METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED` | `True` | bool | Master flag for the safety-net scan. |
| `METATRON_FRESHNESS_SCHEDULED_SCAN_INTERVAL_SECONDS` | `3600` | int | Scan every hour. |
| `METATRON_FRESHNESS_SCAN_BATCH_LIMIT` | `500` | int | Cap per workspace per scan. |
| `METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP` | `False` | bool | One-time flag for env-prefix rollout. |

No new config is read by the producer — the producer already uses
`freshness_enabled` and will continue to enqueue under the new prefixed
key shape automatically because `queue_key_for` centralises the shape.

## FreshnessTarget Protocol delta

```python
# src/metatron/freshness/targets.py

class FreshnessTarget(Protocol):
    ...existing methods...

    async def list_stale_candidates(
        self,
        workspace_id: str,
        *,
        older_than: datetime,
        limit: int,
    ) -> list[str]:
        """Scheduled-scan rescue path. Default = empty. Memory overrides."""
        return []
```

- Default body `return []` means KB's `RawDocumentTarget` is uncharged
  for this ticket (MTRNIX-316 is memory-only per § 8).
- Memory's `MemoryTarget.list_stale_candidates` delegates to a new
  `MemoryPostgresStore.list_stale_candidates(workspace_id, older_than,
  limit)` method.

## CoordinationStore API delta

New methods on `src/metatron/freshness/coordination.py`:

```python
# --- worker identity / heartbeat ---
async def tick_heartbeat(self, worker_id: str, ttl: int) -> None: ...
async def is_worker_alive(self, worker_id: str) -> bool: ...
async def release_worker(self, worker_id: str) -> None: ...

# --- processing-list dequeue ---
async def dequeue_batch(
    self,
    workspace_id: str,
    max_items: int,
    *,
    worker_id: str,
) -> list[FreshnessJob]:
    """LMOVE up to N from the queue to the per-worker processing list.

    The Phase A call-site (`worker.run_once`) passes `worker_id=self._worker_id`.
    Unit tests still pass `worker_id="test-worker"`. Signature is
    kwarg-only so no positional callers break.
    """

async def complete_job(self, worker_id: str, job: FreshnessJob) -> None:
    """LREM the job from the processing list on successful processing."""

# --- reclaim ---
async def list_processing_workers(self) -> list[str]: ...
async def reclaim_worker_orphans(self, worker_id: str) -> int: ...

# --- migration ---
async def drain_legacy_unprefixed(self) -> int: ...
```

Old signature `dequeue_batch(workspace_id, max_items)` → SHIM: emits a
deprecation warning in dev, routes to the new signature with a
test-only `worker_id="compat-noworker"`. This keeps Phase A unit tests
green while coders migrate them in a follow-up PR (NOT in scope for
MTRNIX-316 — we keep backwards compat during the feature merge).
Production call-site (`worker.py`) is migrated in this ticket; the shim
exists only for tests.

## RedisStore API delta

New primitives on `src/metatron/storage/redis.py`:

```python
async def lmove_rightleft(self, src: str, dst: str) -> str | None:
    """LMOVE src dst RIGHT LEFT. Returns the moved value or None."""
    awaitable = cast("Awaitable[str | None]", self._client.lmove(src, dst, "RIGHT", "LEFT"))
    return await awaitable

async def peek_tail(self, key: str) -> str | None:
    """LINDEX key -1."""
    awaitable = cast("Awaitable[str | None]", self._client.lindex(key, -1))
    return await awaitable

async def lrem(self, key: str, value: str, count: int = 1) -> int:
    awaitable = cast("Awaitable[int]", self._client.lrem(key, count, value))
    return int(await awaitable)
```

`redis-py` already supports all three natively; we just wrap them for
type hygiene. `rpop_batch` + `_RPOP_BATCH_LUA` remain in the file for
now (no callers after this ticket, but removal is a cleanup follow-up).

## Key schema — before vs after

| Role | Before (Phase A) | After (MTRNIX-316) |
|---|---|---|
| Queue | `freshness:queue:{ws}` | `freshness:{env}:queue:{ws}` (prefix empty when env unset) |
| Processing | — | `freshness:{env}:processing:{worker_id}` |
| Heartbeat | — | `freshness:{env}:heartbeat:{worker_id}` |
| Reclaim lock | — | `freshness:{env}:reclaim_lock:{worker_id}` |
| Stage lock (memory) | `freshness:{stage}:{target_id}` | `freshness:{env}:{stage}:{target_id}` |
| Stage lock (KB) | `freshness:{stage}:raw_document:{target_id}` | `freshness:{env}:{stage}:raw_document:{target_id}` |

Compatibility note: changing stage-lock key shape means a worker running
mid-upgrade could race with a Phase A worker on the same target. Since
Phase A worker does NOT set the prefix but the new worker DOES, locks
don't interfere — the two shapes are disjoint. Ops impact: during the
rollout window, a pre-MTRNIX-316 worker and a post-MTRNIX-316 worker
could both grab "a" lock on the same record; we accept this as a minor
rollout blip (same trade-off the queue prefix makes, and worker rollout
in staging/prod is single-replica).

## Scheduled-scan module

`src/metatron/freshness/scheduled_scan.py` (new file, L2):

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob
from metatron.freshness import metrics
from metatron.freshness.coordination import CoordinationStore
from metatron.freshness.targets import FreshnessTarget

logger = structlog.get_logger()


@dataclass
class ScheduledScan:
    target_kind: str
    target: FreshnessTarget
    coordination: CoordinationStore
    workspace_lister: Callable[[], Awaitable[list[str]]]
    stale_after_days: int
    batch_limit: int

    async def run(self) -> int:
        """Enqueue stale candidates for all workspaces. Returns total enqueued."""
        settings = get_settings()
        older_than = datetime.now(UTC) - timedelta(days=self.stale_after_days)
        total = 0
        try:
            workspaces = await self.workspace_lister()
        except Exception:
            logger.warning("freshness.scheduled_scan.list_workspaces_failed", exc_info=True)
            metrics.scheduled_scan_errors.labels(env=settings.env, target_kind=self.target_kind).inc()
            return 0
        for ws in workspaces:
            try:
                ids = await self.target.list_stale_candidates(
                    ws, older_than=older_than, limit=self.batch_limit
                )
                for rid in ids:
                    await self.coordination.enqueue_job(
                        FreshnessJob(
                            workspace_id=ws,
                            event_type="scheduled_scan",
                            target_kind=self.target_kind,
                            target_id=rid,
                            payload={"older_than_iso": older_than.isoformat()},
                        )
                    )
                if ids:
                    metrics.scheduled_scan_jobs_enqueued.labels(
                        env=settings.env, target_kind=self.target_kind,
                    ).inc(len(ids))
                    total += len(ids)
                    logger.info(
                        "freshness.scheduled_scan.enqueued",
                        workspace_id=ws,
                        target_kind=self.target_kind,
                        count=len(ids),
                    )
            except Exception:
                logger.warning(
                    "freshness.scheduled_scan.failed",
                    workspace_id=ws,
                    target_kind=self.target_kind,
                    exc_info=True,
                )
                metrics.scheduled_scan_errors.labels(
                    env=settings.env, target_kind=self.target_kind,
                ).inc()
        return total
```

Workspace lister: `PostgresStore.list_workspaces()` already exists and
is used by sync-logs recovery (MTRNIX-309). Injected as a callable so
the scan module stays storage-agnostic and testable.

## Worker changes

`src/metatron/memory/freshness/worker.py` changes, summarised:

1. `_build_worker` populates a `worker_id`, wires `ScheduledScan`
   instances (one per target_kind — only memory in this ticket), and
   returns a `FreshnessWorker` with the new kwargs.
2. `FreshnessWorker.__init__` accepts:
   - `worker_id: str`
   - `scheduled_scanners: list[ScheduledScan] | None = None`
   - `heartbeat_ttl: int | None = None`
   - `reclaim_interval_iterations: int | None = None`
   - `scheduled_scan_interval_seconds: int | None = None`
3. `_run_loop`:
   - At entry: `await coord.tick_heartbeat(...)`, then
     `await worker._reclaim_orphans()`, then
     `await coord.drain_legacy_unprefixed()` iff flag set.
   - Inside loop: at the top of each iteration,
     `await coord.tick_heartbeat(...)`; every `reclaim_interval`
     iterations, `_reclaim_orphans()`; check the scan timer and call
     each scanner's `.run()` if due.
   - On `CancelledError` / hard exit: `await coord.release_worker(worker_id)`
     best-effort so a clean shutdown empties the heartbeat key proactively.
4. `run_once`:
   - Passes `worker_id=self._worker_id` to `dequeue_batch`.
   - In the job processing `finally` block, calls
     `coord.complete_job(worker_id, job)` after the existing
     `save_machine_event(freshness_job_processed)`.

`_process_job` is otherwise unchanged — LREM happens in the outer
`run_once` finally.

## Failure modes

| Scenario | Behaviour | Observed via |
|---|---|---|
| SIGKILL mid-batch | Jobs sit on processing list; next live worker (or self on restart) reclaims via `LMOVE` back to queue; eventually processed twice if the original worker had already committed PG for one; idempotent stages handle it | `freshness_orphans_reclaimed_total` + `freshness.reclaim.*` logs |
| Redis down during reclaim | `LMOVE` raises; swallowed; `freshness_reclaim_errors_total` bumps; next iteration tries again | counter + WARNING log |
| Redis down during `tick_heartbeat` | `SET` raises; swallowed; heartbeat key stays expired; external reclaimer eventually spots us as dead; we get reclaimed (false positive). Next tick succeeds; we log `freshness.reclaim.race` when we LREM nothing. | counter + INFO log |
| Worker-id collision (two workers pick the same id) | UUID suffix makes this practically impossible (1 in 4 billion per restart); if it happened, they'd share a processing list and LREM would still work (one owns each entry by value match). Documented; not defended | — |
| Scheduled scan while PG down | `list_workspaces` raises; swallowed; error counter ticks; next cycle retries | counter + WARNING |
| Scheduled scan enqueues duplicate of a recently-processed record | `freshness_job_received` MachineEvent tracks idempotency; stage locks prevent double-run | existing behaviour |
| Env prefix flip (dev rig adds `METATRON_ENV=development`) | Legacy drain at startup moves any unprefixed queue jobs into the prefixed equivalent | `freshness_legacy_keys_drained_total` |
| Worker processes everything but Redis goes down before `LREM` | Next reclaim pass moves the "orphan" back, pipeline re-processes idempotently | counter + log |
| A worker never restarts; a peer crashed | The live worker runs reclaim every ~60s and picks up the peer's orphans | counter + log |
| Two live workers see the same dead worker | Both try to acquire `reclaim_lock:{worker_id}` via SET NX EX; only one wins; the other skips. When winner releases, the other may run the next iteration if orphans are left (normally they're not) | existing behaviour |
| Scheduled scan finds a target whose `list_stale_candidates` is the default (empty) | Zero jobs enqueued, scan completes cleanly — KB exactly | silent |

## Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `LMOVE` loop adds Redis RTT overhead | LOW | Quantified in § 6 (~1% iteration overhead). Pipelining as a future optimisation. |
| Protocol method default-body change leaks into KB | LOW | Default returns `[]`. KB scheduled scan is a separate ticket. Unit test asserts KB target's default behaviour. |
| Env prefix rollout breaks existing dev rigs | LOW | Empty-env fallback preserves Phase A key shape byte-identically. Legacy drain is flag-gated. |
| Integration test SIGKILL flaky in CI | MEDIUM | Use an explicit processing-list `LLEN` poll (not `time.sleep`) to confirm batch was popped before killing. Test harness timeout 30s. |
| False-positive "dead worker" during GC pause | LOW | Heartbeat TTL = 20s = 10× typical worker poll. Python GC pauses are sub-second. |
| Reclaim counter cardinality explodes with worker churn | LOW | Label is `worker_id_hash` (4 hex = 65k ceiling), not raw id. |
| `list_workspaces` scan cost grows linearly with tenant count | LOW | Already used by sync-logs recovery at the same cadence. No regression. |
| Backwards-compat shim for old `dequeue_batch(ws, N)` signature introduces divergent behaviour | LOW | Shim is test-only; prod wiring passes `worker_id`. Deprecation warning flags call sites for follow-up. |

## Coordination points

- **`core/interfaces.py`** — unchanged.
- **`core/events.py`** — unchanged. No new event constants (scheduled-scan
  enqueue uses existing `event_type="scheduled_scan"` on `FreshnessJob`,
  already reserved in the Phase A producer).
- **`core/models.py`** — unchanged. `FreshnessJob.event_type` is a
  free-form string; new values don't require schema changes.
- **`FreshnessTarget` Protocol** — one new optional method with a default
  body. KB adapter (RawDocumentTarget) unchanged (uses the default).
- **Enterprise repo** — no coordination needed. New Prometheus counters
  (`freshness_orphans_reclaimed_total`, `freshness_reclaim_errors_total`,
  `freshness_scheduled_scan_jobs_enqueued_total`,
  `freshness_scheduled_scan_errors_total`,
  `freshness_legacy_keys_drained_total`) — PR body courtesy mention for
  enterprise Grafana dashboards.
- **`docs/MEMORY_MCP_FOLLOWUPS.md`** — add a note: "KB scheduled scan is
  deferred — implement `RawDocumentTarget.list_stale_candidates` and wire
  a second `ScheduledScan` instance in `_build_worker`." Small follow-up.
- **Ops runbook** — when `freshness_reclaim_errors_total` rate > 0 for
  10 minutes: check Redis health; when
  `freshness_scheduled_scan_errors_total` rate > 0: check PG.
  `freshness_orphans_reclaimed_total > 0` is informational (expected
  during worker restarts), not a page.

## Acceptance criteria (reviewer checklist, restated testably)

1. `make lint` — zero errors on changed files.
2. `make typecheck` — zero errors (mypy strict).
3. `make test` — Phase A/B/C unit tests unchanged; new unit tests green.
4. `make test-all` — integration suite green against live PG + Qdrant + Redis.
5. **SIGKILL integration test** passes: subprocess worker → seed + enqueue
   N jobs → kill mid-batch → second worker reclaims → all N jobs
   eventually reach `freshness_job_processed` MachineEvent. No job lost.
6. **Env-prefix integration test** passes: worker A with env=staging and
   worker B with env=development each see only their own queue.
7. **Scheduled-scan integration test** passes: seeded stale records get
   enqueued and transitioned to `STALE`/`ARCHIVED` without a write event.
8. Grep sanity:
   - `grep -rn "rpop_batch" src/metatron/freshness/` → only in comments
     / deprecation notes (prod call-site is `lmove_rightleft`).
   - `grep -rn "freshness:queue:" src/` → only in `coordination.py` as a
     key-shape constant.
9. `METATRON_FRESHNESS_ENABLED=false` — worker exits immediately; no new
   Redis keys touched.
10. `core/interfaces.py` unchanged. `core/events.py` unchanged.
11. PR body mentions the 5 new Prometheus counters.
12. Redis version requirement note in `CHANGELOG.md` (>= 6.2.0).
