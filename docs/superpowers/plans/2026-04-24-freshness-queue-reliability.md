# Freshness queue reliability — processing-list reclaim + scheduled scan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** replace the lossy atomic-batch LPOP in `CoordinationStore.dequeue_batch` with a `LMOVE`-into-per-worker processing list, add a periodic reclaim pass that rescues orphaned processing lists from dead workers, add a scheduled-scan safety-net task inside the worker loop, and namespace every freshness Redis key with the existing `METATRON_ENV` value. Five new Prometheus counters for observability. No PG schema change. No `core/interfaces.py` / `core/events.py` change. Backwards-compatible when `METATRON_ENV` is unset (empty prefix → Phase A key shape).

**Architecture:**
- Redis primitives — add `lmove_rightleft`, `peek_tail`, `lrem` to `RedisStore` (L1).
- Coordination — new methods on `CoordinationStore` for heartbeat, processing-list dequeue/complete, orphan reclaim, legacy drain (L2).
- Target — optional `FreshnessTarget.list_stale_candidates` with default `return []`; memory adapter overrides it via a new `MemoryPostgresStore.list_stale_candidates` (L3).
- Scheduled scan — new `scheduled_scan.py` module; worker wires one instance per target kind (L2).
- Worker — build `worker_id` at boot, heartbeat each iteration, reclaim on startup + every N iterations, run scheduled scan on a timer.
- Env prefix — `METATRON_ENV` drives `freshness:{env}:*` key shape; empty env keeps Phase A shape.

**Tech Stack:** Python 3.12, asyncio, `redis.asyncio` (Redis >= 6.2 required for `LMOVE`), SQLAlchemy async (asyncpg), `prometheus_client` (optional dep), structlog, pytest (`asyncio_mode = "auto"`), subprocess + `os.kill` for the SIGKILL integration test.

**Jira:** MTRNIX-316
**Depends on:** MTRNIX-304 (merged), MTRNIX-313 (merged), MTRNIX-322 (merged).
**Spec:** `docs/superpowers/specs/2026-04-24-freshness-queue-reliability-design.md`
**Branch:** `feature/MTRNIX-316` (already checked out).

---

## Layer Boundary Summary

| File | Layer | Allowed imports |
|---|---|---|
| `src/metatron/storage/redis.py` (extend) | L1 | `redis.asyncio` only |
| `src/metatron/freshness/coordination.py` (extend) | L2 | `core.config`, `core.models`, `storage.redis`, `freshness.metrics` |
| `src/metatron/freshness/metrics.py` (extend) | L2 | `prometheus_client` (optional) |
| `src/metatron/freshness/worker_id.py` (new) | L2 | stdlib only (`os`, `socket`, `uuid`) |
| `src/metatron/freshness/scheduled_scan.py` (new) | L2 | `core.config`, `core.models`, `freshness.coordination`, `freshness.metrics`, `freshness.targets` |
| `src/metatron/freshness/targets.py` (extend) | L2 | no new imports |
| `src/metatron/memory/freshness/target_memory.py` (extend) | L3 | `storage.memory_postgres`, existing |
| `src/metatron/memory/freshness/worker.py` (extend) | L3 | same as today + `freshness.worker_id`, `freshness.scheduled_scan` |
| `src/metatron/storage/memory_postgres.py` (extend) | L1 | existing |
| `src/metatron/core/config.py` (extend) | L0 | existing |

**Not touched:** `core/interfaces.py`, `core/events.py`, `core/models.py`, `storage/postgres.py` (apart from if `list_workspaces` needs a thin confirmation), `storage/memory_qdrant.py`, `memory/service.py`, `memory/search.py`, `mcp/tools/*`, `ingestion/freshness/*`, `api/*`.

**No upward imports.** Memory worker (L3) depends on shared freshness (L2); shared freshness depends on storage (L1) and core (L0). No reverse edges introduced.

---

## Config Vars (new, all `METATRON_` prefixed)

| Var | Default | Purpose |
|---|---|---|
| `METATRON_FRESHNESS_HEARTBEAT_TTL_SECONDS` | `20` | Heartbeat key TTL. Reclaim considers a worker dead when the key is missing. |
| `METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS` | `30` | Reclaim pass cadence inside the worker loop. |
| `METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED` | `True` | Master flag for the safety-net scan. |
| `METATRON_FRESHNESS_SCHEDULED_SCAN_INTERVAL_SECONDS` | `3600` | Scan cadence. |
| `METATRON_FRESHNESS_SCAN_BATCH_LIMIT` | `500` | Cap per-workspace stale candidates enqueued per scan. |
| `METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP` | `False` | One-time flag for the env-prefix rollout (legacy unprefixed → prefixed drain). |

Reuses existing `METATRON_ENV` for the key prefix (no new var for that).

---

## Event Constants

**None added.** `core/events.py` unchanged. `FreshnessJob.event_type="scheduled_scan"` is already a valid free-form value (Phase A producer reserves it — see `memory/freshness/producer.py` docstring).

---

## Backward Compatibility Guarantee

- `CoordinationStore.enqueue_job` signature unchanged; wire format of serialised jobs unchanged (producer call sites untouched).
- `CoordinationStore.dequeue_batch` signature changes to require `worker_id` (kwarg-only); a thin compatibility shim accepts calls without `worker_id` for Phase A unit tests (emits DeprecationWarning; synthesises a test worker id).
- Producer path unchanged — `enqueue_if_enabled` still calls `coordination.enqueue_job`. The key shape inside `queue_key_for` now consults `settings.env`. When `METATRON_ENV` is unset or empty, the key shape is byte-identical to Phase A.
- `FreshnessTarget` Protocol gains one method with a default body (`return []`). KB adapter (`RawDocumentTarget`) keeps default behaviour — MTRNIX-313 tests stay green.
- Phase A (MTRNIX-304) + Phase B (MTRNIX-313) + MTRNIX-314 + MTRNIX-322 tests stay green.
- Worker started without `METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED` set inherits the default `True` — safety net is on by default. To preserve legacy dev-rig behaviour exactly, ops may set it to `False`; in a greenfield deploy leaving it on adds only one background DB query per hour.
- Prometheus counters are additive; scrapers tolerate new series.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/metatron/storage/redis.py` | Add async wrappers: `lmove_rightleft`, `peek_tail`, `lrem`. |
| Modify | `src/metatron/core/config.py` | Add six new `freshness_*` settings (heartbeat, reclaim cadence, scheduled scan, batch limit, drain flag). |
| Modify | `src/metatron/freshness/metrics.py` | Add five new counters (+ noop fallbacks + `__all__` entries). |
| Create | `src/metatron/freshness/worker_id.py` | `build_worker_id() -> str` helper. Composes `{hostname}:{pid}:{short-uuid}`. Supports `METATRON_FRESHNESS_TEST_WORKER_ID` env override for integration tests. |
| Modify | `src/metatron/freshness/coordination.py` | Prefix queue/processing/heartbeat/lock keys with `settings.env`; add methods: `tick_heartbeat`, `is_worker_alive`, `release_worker`, `complete_job`, `list_processing_workers`, `reclaim_worker_orphans`, `drain_legacy_unprefixed`. Rework `dequeue_batch` to take `worker_id` kwarg and use `LMOVE`. Keep the old signature as a deprecation-warn shim for unit tests. |
| Modify | `src/metatron/freshness/targets.py` | Add `list_stale_candidates` to the Protocol with a default `return []` body. |
| Create | `src/metatron/freshness/scheduled_scan.py` | `ScheduledScan` dataclass + `run()` method. |
| Modify | `src/metatron/memory/freshness/target_memory.py` | Override `list_stale_candidates` → delegates to `MemoryPostgresStore.list_stale_candidates`. |
| Modify | `src/metatron/storage/memory_postgres.py` | Add `list_stale_candidates(workspace_id, older_than, limit) -> list[str]` — SELECT id WHERE workspace_id, status NOT IN ('stale','superseded','archived'), updated_at < :older_than ORDER BY updated_at ASC LIMIT :limit. |
| Modify | `src/metatron/memory/freshness/worker.py` | Build `worker_id` at bootstrap; call `tick_heartbeat` + `reclaim_orphans` + `drain_legacy_unprefixed` at startup; tick heartbeat per iteration; reclaim every N iterations; run scheduled scans on a timer; pass `worker_id` to `dequeue_batch`; call `complete_job` in the job `finally`. Release worker on graceful shutdown. |
| Create | `tests/unit/storage/test_redis_lmove.py` | Unit tests: `lmove_rightleft` returns moved value, None on empty; `peek_tail`; `lrem`. Uses `fakeredis.aioredis` if available, otherwise `pytest.importorskip`. |
| Create | `tests/unit/freshness/test_coordination_heartbeat.py` | Unit tests: tick + exists/missing; release; prefix when env set vs empty. |
| Create | `tests/unit/freshness/test_coordination_processing_list.py` | Unit tests: `dequeue_batch(worker_id=...)` moves jobs to processing list; `complete_job` LREMs; orphan detection via `list_processing_workers`; `reclaim_worker_orphans` drains dead worker back to source workspace queue; race — simulate concurrent reclaim on same worker (second call acquires lock fails, returns 0). |
| Create | `tests/unit/freshness/test_coordination_env_prefix.py` | Unit tests: `METATRON_ENV="development"` → prefixed keys; unset → unprefixed; `drain_legacy_unprefixed` moves old→new. |
| Create | `tests/unit/freshness/test_worker_id.py` | Unit tests: uniqueness across calls; shape; env override for tests. |
| Create | `tests/unit/freshness/test_scheduled_scan.py` | Unit tests: calls `target.list_stale_candidates` per workspace; enqueues `scheduled_scan` jobs with correct payload; counter increments; empty-workspaces path; per-workspace error swallow. |
| Create | `tests/unit/memory/freshness/test_memory_target_stale_candidates.py` | Unit tests: `MemoryTarget.list_stale_candidates` delegates; `MemoryPostgresStore.list_stale_candidates` filters + orders + limits. |
| Create | `tests/unit/memory/freshness/test_worker_reclaim_loop.py` | Unit tests: `_run_loop` calls reclaim once at startup; subsequent reclaim every N iterations; heartbeat ticked; scheduled scan timer fires on time. |
| Create | `tests/integration/memory/freshness/test_reclaim_sigkill.py` | Integration: subprocess worker + SIGKILL + second worker reclaims. Live PG + Qdrant + Redis. |
| Create | `tests/integration/memory/freshness/test_scheduled_scan_enqueues_stale.py` | Integration: seed stale records; run one `ScheduledScan.run()`; assert jobs enqueued. |
| Create | `tests/integration/memory/freshness/test_env_prefix_isolation.py` | Integration: worker A (env=staging) + worker B (env=development) — enqueue under A's key; B never sees it. |
| Modify | `docs/MEMORY_MCP_FOLLOWUPS.md` | Add short entry: "KB scheduled scan is deferred — implement `RawDocumentTarget.list_stale_candidates` and wire a second `ScheduledScan` in `_build_worker`. Follow-up to MTRNIX-316." |
| Modify | `src/metatron/memory/.claude/CLAUDE.md` | Add bullet to `freshness/worker.py`: "worker_id-based processing list reclaim + scheduled scan (MTRNIX-316)." Update `freshness/target_memory.py` bullet: "`list_stale_candidates` delegates to `MemoryPostgresStore.list_stale_candidates` for the scheduled-scan safety net (MTRNIX-316)." |
| Modify | `src/metatron/storage/.claude/claude.md` | Under `redis.py`, add bullet: "`lmove_rightleft`, `peek_tail`, `lrem` — primitives for the freshness processing-list reclaim pattern (MTRNIX-316)." Under `memory_postgres.py`, add bullet: "`list_stale_candidates(workspace_id, older_than, limit)` — scheduled-scan rescue path (MTRNIX-316)." |
| Modify | `CHANGELOG.md` | Entry: "feat(freshness): processing-list reclaim + scheduled-scan safety net + env-prefixed Redis keys (MTRNIX-316). Requires Redis >= 6.2 for `LMOVE`. Adds five Prometheus counters: `freshness_orphans_reclaimed_total`, `freshness_reclaim_errors_total`, `freshness_scheduled_scan_jobs_enqueued_total`, `freshness_scheduled_scan_errors_total`, `freshness_legacy_keys_drained_total`." |
| Modify | `docker-compose.yml` | Add comment near the redis service: `# Redis >= 6.2 required for LMOVE (MTRNIX-316)`. Confirm the pinned image (`redis:7-alpine`) already satisfies this. |

Total: **10 modified code files + 3 modified docs + 1 CHANGELOG + 1 compose comment + 2 new source files + 8 new test files (6 unit, 3 integration — wait: 6 unit files below, 3 integration). Correction: 7 unit + 3 integration = 10 new test files.**

---

## Ordered Tasks

Execute in order. After **every** task, run `make lint`, `make typecheck`, `make test` as three separate commands (never chain with `;` or `&&`, per the user's global rule).

---

### Task 1: Redis primitives — `lmove_rightleft`, `peek_tail`, `lrem`

**Files:**
- Modify: `src/metatron/storage/redis.py`
- Create: `tests/unit/storage/test_redis_lmove.py`

- [ ] **Step 1: Write unit tests first (TDD).**
  Cases:
  - `lmove_rightleft`: src has `["a","b","c"]` (LPUSH order → `c,b,a` in Redis); call → moves tail `a` to dst head; assert returned value equals `"a"`; assert src now `["c","b"]`, dst `["a"]`.
  - `lmove_rightleft` on empty src: returns `None`; src/dst unchanged.
  - `peek_tail` on list of 3: returns tail value without mutating.
  - `peek_tail` on missing key: returns `None`.
  - `lrem` with matching value and `count=1`: removes one; returns 1.
  - `lrem` with non-matching value: returns 0.

- [ ] **Step 2: Add the three methods to `RedisStore`.**
  Follow the existing pattern — `cast("Awaitable[...]", self._client.<cmd>(...))` for typing hygiene. Use `redis-py`'s `lmove`, `lindex`, `lrem` directly.

- [ ] **Step 3: Lint + typecheck + test.** Three separate commands.

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/storage/redis.py tests/unit/storage/test_redis_lmove.py
  git commit -m "feat(MTRNIX-316): RedisStore primitives — lmove_rightleft, peek_tail, lrem"
  ```

**Acceptance:** Six unit tests green.

---

### Task 2: Settings — six new `freshness_*` knobs

**Files:**
- Modify: `src/metatron/core/config.py`
- Create: `tests/unit/core/test_config_freshness_reliability.py`

- [ ] **Step 1: Write unit tests first.**
  - Defaults: `heartbeat_ttl_seconds=20`, `reclaim_interval_iterations=30`, `scheduled_scan_enabled=True`, `scheduled_scan_interval_seconds=3600`, `scan_batch_limit=500`, `drain_legacy_at_startup=False`.
  - Env override: set each var; assert parsed value.
  - Boolean parsing: `"false"` / `"FALSE"` / `"0"` → False.

- [ ] **Step 2: Add six `Field(...)` entries** in the Freshness pipeline section (right after `freshness_max_consecutive_errors`). Use the exact alias names from the Config Vars table above.

- [ ] **Step 3: Lint + typecheck + test.**

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/core/config.py tests/unit/core/test_config_freshness_reliability.py
  git commit -m "feat(MTRNIX-316): six new METATRON_FRESHNESS_* reliability settings"
  ```

---

### Task 3: Prometheus counters

**Files:**
- Modify: `src/metatron/freshness/metrics.py`
- Modify: `src/metatron/memory/freshness/metrics.py` (re-export shim)

- [ ] **Step 1: Add five new `Any` declarations** alongside `qdrant_sync_failed`:
  `orphans_reclaimed`, `reclaim_errors`, `scheduled_scan_jobs_enqueued`, `scheduled_scan_errors`, `legacy_keys_drained`.

- [ ] **Step 2: Inside the `try: from prometheus_client import ...` block,** define the five real `Counter(...)` instances using the metric names and labels from the spec § 12.

- [ ] **Step 3: Inside the `except ImportError:` block,** assign each to `_NoopMetric()`.

- [ ] **Step 4: Add all five to `__all__`** alphabetically.

- [ ] **Step 5: Re-export from the memory shim** (`src/metatron/memory/freshness/metrics.py`): extend the `from metatron.freshness.metrics import ...` tuple and the shim's `__all__`.

- [ ] **Step 6: Lint + typecheck + test.**

- [ ] **Step 7: Commit.**
  ```
  git add src/metatron/freshness/metrics.py src/metatron/memory/freshness/metrics.py
  git commit -m "feat(MTRNIX-316): five new Prometheus counters for reclaim + scheduled scan"
  ```

**Acceptance:** `from metatron.freshness.metrics import orphans_reclaimed` (and the other four) succeeds; `.labels(...).inc()` is a no-op-safe call.

---

### Task 4: `build_worker_id` helper

**Files:**
- Create: `src/metatron/freshness/worker_id.py`
- Create: `tests/unit/freshness/test_worker_id.py`

- [ ] **Step 1: Write unit tests first.**
  - `build_worker_id()` returns a string matching `^[^:]+:\d+:[0-9a-f]{8}$`.
  - Two calls return different values (uuid suffix differs).
  - With `METATRON_FRESHNESS_TEST_WORKER_ID=my-fixed-id` env var set, the function returns `"my-fixed-id"` verbatim.

- [ ] **Step 2: Implement `build_worker_id`.**
  ```python
  import os, socket, uuid
  def build_worker_id() -> str:
      override = os.environ.get("METATRON_FRESHNESS_TEST_WORKER_ID")
      if override:
          return override
      return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
  ```

- [ ] **Step 3: Lint + typecheck + test.**

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/freshness/worker_id.py tests/unit/freshness/test_worker_id.py
  git commit -m "feat(MTRNIX-316): build_worker_id() helper with test-env override"
  ```

---

### Task 5: `CoordinationStore` — env prefix + heartbeat + processing-list dequeue

**Files:**
- Modify: `src/metatron/freshness/coordination.py`
- Create: `tests/unit/freshness/test_coordination_env_prefix.py`
- Create: `tests/unit/freshness/test_coordination_heartbeat.py`
- Create: `tests/unit/freshness/test_coordination_processing_list.py`

- [ ] **Step 1: Write `test_coordination_env_prefix.py` first (TDD).**
  - With `monkeypatch.setattr(settings, "env", "development")`: `queue_key_for("ws-1")` returns `"freshness:development:queue:ws-1"`.
  - With `settings.env = ""`: returns `"freshness:queue:ws-1"` (legacy).
  - Stage-lock key pattern prefixed the same way.
  - `list_active_workspaces` matches only the current env prefix (seed keys under two envs, assert only one env's keys are returned).

- [ ] **Step 2: Refactor key helpers.**
  Replace the module-level constants `_QUEUE_PREFIX`, `_LOCK_PREFIX` with a single `_key_prefix() -> str` helper that reads `settings.env`. All key builders (`queue_key_for`, `_lock_key`, plus new ones below) go through `_key_prefix()`.

- [ ] **Step 3: Write `test_coordination_heartbeat.py`.**
  - `tick_heartbeat(worker_id, ttl=5)` sets a key with TTL; `is_worker_alive(worker_id)` → True; `await asyncio.sleep(6)` on fakeredis → False.
  - `release_worker(worker_id)` deletes the key; `is_worker_alive` → False immediately.

- [ ] **Step 4: Implement `tick_heartbeat`, `is_worker_alive`, `release_worker`.**
  Heartbeat key shape: `freshness:{env}:heartbeat:{worker_id}`. Use plain `SET key worker_id EX ttl` (not NX) — idempotent upsert. `is_worker_alive` uses `EXISTS` and returns False on any Redis exception (fail-closed).

- [ ] **Step 5: Write `test_coordination_processing_list.py`.**
  - Enqueue N jobs on workspace `ws-A`; `dequeue_batch(ws-A, 5, worker_id="w1")` returns 5 jobs AND leaves them on processing list `freshness:{env}:processing:w1`.
  - After `complete_job("w1", job)`, processing list shrinks by 1.
  - `list_processing_workers` returns `["w1"]`.
  - Deprecation shim: `dequeue_batch(ws, 5)` (no `worker_id`) issues a `DeprecationWarning`, uses a synthetic worker id.

- [ ] **Step 6: Rework `dequeue_batch` + add `complete_job`.**
  - Signature: `dequeue_batch(workspace_id, max_items, *, worker_id)`.
  - Body: loop up to `max_items` times, `raw = await self._redis.lmove_rightleft(queue_key_for(ws), processing_key_for(worker_id))`; break on None; try-parse; skip poison (same log line as today). Return the collected `FreshnessJob` list. Poison items stay on the processing list — they get cleaned up by later `lrem`; defer to the existing poison-handling docstring in `_deserialize_job`.
  - Compat shim: define the old signature as `def dequeue_batch(self, workspace_id, max_items)` via `*args` inspection; emit `warnings.warn("…", DeprecationWarning, stacklevel=2)`; call the new method with `worker_id=_compat_worker_id()`.
  - `complete_job(worker_id, job)`: `await self._redis.lrem(processing_key_for(worker_id), _serialize_job(job), count=1)`.
  - New helper `processing_key_for(worker_id) -> str` mirrors `queue_key_for`.

- [ ] **Step 7: Add `list_processing_workers`.**
  `SCAN freshness:{env}:processing:*` via existing `scan_keys` helper. Strip prefix; return worker ids (sorted). Swallow exceptions → return `[]` (reclaim pass degrades gracefully).

- [ ] **Step 8: Lint + typecheck + test.**

- [ ] **Step 9: Commit.**
  ```
  git add src/metatron/freshness/coordination.py tests/unit/freshness/test_coordination_env_prefix.py tests/unit/freshness/test_coordination_heartbeat.py tests/unit/freshness/test_coordination_processing_list.py
  git commit -m "feat(MTRNIX-316): env-prefixed Redis keys + heartbeat + processing-list dequeue"
  ```

**Acceptance:** All unit tests green. `grep -rn "freshness:queue:" src/` → only inside `queue_key_for` and its call-through.

---

### Task 6: `CoordinationStore` — reclaim + legacy drain

**Files:**
- Modify: `src/metatron/freshness/coordination.py`
- Extend: `tests/unit/freshness/test_coordination_processing_list.py`

- [ ] **Step 1: Extend the test file with reclaim + drain cases.**
  - Reclaim happy path: worker `w1` popped 3 jobs to its processing list; `release_worker("w1")` (simulate death); from worker `w2` call `reclaim_worker_orphans("w1")` — returns 3; `queue_key_for(ws)` now has the 3 jobs back; `processing:w1` is empty.
  - Reclaim skips live worker: w1 is alive (heartbeat); reclaim returns 0.
  - Reclaim concurrency: simulate two calls to `reclaim_worker_orphans("w1")` racing — first acquires lock, second gets the lock-busy branch and returns 0.
  - Reclaim race on LREM: pre-LMOVE, remove the tail manually (simulates a late live-worker LREM); `LMOVE` returns None on next iteration; loop exits; returned count is correct.
  - `drain_legacy_unprefixed`: seed unprefixed `freshness:queue:ws-x` with 2 jobs; with `settings.env="development"`, call the drain; assert prefixed `freshness:development:queue:ws-x` has 2 jobs and unprefixed is empty; counter incremented by 2.

- [ ] **Step 2: Implement `reclaim_worker_orphans`.**
  Follows the spec § 5 algorithm:
  ```python
  async def reclaim_worker_orphans(self, worker_id: str) -> int:
      if await self.is_worker_alive(worker_id):
          return 0
      lock_key = f"{_key_prefix()}reclaim_lock:{worker_id}"
      token = uuid4().hex
      if not await self._redis.acquire_lock(lock_key, 30, token):
          return 0
      recovered = 0
      processing_key = processing_key_for(worker_id)
      try:
          while True:
              raw = await self._redis.peek_tail(processing_key)
              if raw is None:
                  break
              job = _deserialize_job(raw)
              if job is None:
                  # poison — drop from processing list to avoid infinite loop
                  await self._redis.lrem(processing_key, raw, count=1)
                  continue
              dst = queue_key_for(job.workspace_id)
              moved = await self._redis.lmove_rightleft(processing_key, dst)
              if moved is None:
                  break  # race: list emptied under us
              recovered += 1
              settings = get_settings()
              wid_hash = hashlib.sha1(worker_id.encode()).hexdigest()[:4]
              metrics.orphans_reclaimed.labels(env=settings.env, worker_id_hash=wid_hash).inc()
      finally:
          await self._redis.release_lock(lock_key, token)
      return recovered
  ```

- [ ] **Step 3: Implement `drain_legacy_unprefixed`.**
  Only meaningful when `_key_prefix() != "freshness:"` (i.e. env is set):
  ```python
  async def drain_legacy_unprefixed(self) -> int:
      settings = get_settings()
      if not settings.env:
          return 0
      legacy_keys = await self._redis.scan_keys("freshness:queue:*")
      # Filter out prefixed keys accidentally matching (e.g. env "queue")
      # by excluding anything with more than one ":" between "freshness:" and the remainder.
      legacy_keys = [k for k in legacy_keys if k.count(":") == 2 and not k.startswith(f"freshness:{settings.env}:")]
      moved = 0
      for k in legacy_keys:
          ws = k.split(":", 2)[2]
          new_key = queue_key_for(ws)  # prefixed
          while True:
              v = await self._redis.lmove_rightleft(k, new_key)
              if v is None:
                  break
              moved += 1
      if moved:
          metrics.legacy_keys_drained.labels(env=settings.env).inc(moved)
      return moved
  ```
  Swallow exceptions at the outer caller (the worker) — not inside this method; we want tests to be able to assert on raises from a truly-broken Redis.

- [ ] **Step 4: Lint + typecheck + test.**

- [ ] **Step 5: Commit.**
  ```
  git add src/metatron/freshness/coordination.py tests/unit/freshness/test_coordination_processing_list.py
  git commit -m "feat(MTRNIX-316): orphan reclaim + legacy key drain"
  ```

---

### Task 7: `FreshnessTarget` protocol + memory adapter override

**Files:**
- Modify: `src/metatron/freshness/targets.py`
- Modify: `src/metatron/memory/freshness/target_memory.py`
- Modify: `src/metatron/storage/memory_postgres.py`
- Create: `tests/unit/memory/freshness/test_memory_target_stale_candidates.py`

- [ ] **Step 1: Write unit tests first.**
  - `MemoryPostgresStore.list_stale_candidates(ws, older_than, limit=10)` — seed rows with `updated_at` both before and after the threshold, different statuses (`ACTIVE`, `STALE`, `ARCHIVED`). Assert only non-terminal-status rows older than `older_than` are returned, ordered ASC by `updated_at`, up to `limit`.
  - `MemoryTarget.list_stale_candidates` — mock `MemoryPostgresStore`; assert it forwards args 1:1.
  - Default `FreshnessTarget.list_stale_candidates` via a minimal mock class that does not override — returns `[]`.

- [ ] **Step 2: Extend the Protocol.**
  In `targets.py`, add the method with a default body:
  ```python
  async def list_stale_candidates(
      self,
      workspace_id: str,
      *,
      older_than: datetime,
      limit: int,
  ) -> list[str]:
      return []
  ```
  Note: Python Protocols can provide default method bodies only if they inherit from `Protocol` with no methods in `__init_subclass__` gymnastics — if mypy complains, make it a regular ABC-style base class OR add the method as a required Protocol member and implement the default in a mixin. Simpler path: add the method to the Protocol as required (no default) and add implementations in BOTH concrete classes (`RawDocumentTarget` → `return []`, `MemoryTarget` → delegate). Pick whichever passes mypy strict — see `freshness/targets.py` current shape; if other methods already have bodies (ABC style), follow suit. If strict Protocol, define in both.

- [ ] **Step 3: Implement `MemoryPostgresStore.list_stale_candidates`.**
  ```python
  async def list_stale_candidates(
      self,
      workspace_id: str,
      *,
      older_than: datetime,
      limit: int = 500,
  ) -> list[str]:
      async with self._engine.begin() as conn:
          result = await conn.execute(
              text("""
                  SELECT id
                  FROM memory_records
                  WHERE workspace_id = :ws
                    AND status NOT IN ('stale', 'superseded', 'archived')
                    AND updated_at < :older_than
                  ORDER BY updated_at ASC
                  LIMIT :limit
              """),
              {"ws": workspace_id, "older_than": older_than, "limit": limit},
          )
          return [row[0] for row in result.fetchall()]
  ```

- [ ] **Step 4: Implement `MemoryTarget.list_stale_candidates`.**
  Thin delegate to `self._pg_store.list_stale_candidates(...)`.

- [ ] **Step 5: If KB uses a non-default Protocol (see Step 2 note), add the `return []` to `RawDocumentTarget` explicitly.**

- [ ] **Step 6: Lint + typecheck + test.**

- [ ] **Step 7: Commit.**
  ```
  git add src/metatron/freshness/targets.py src/metatron/memory/freshness/target_memory.py src/metatron/storage/memory_postgres.py tests/unit/memory/freshness/test_memory_target_stale_candidates.py
  git commit -m "feat(MTRNIX-316): FreshnessTarget.list_stale_candidates + memory implementation"
  ```

---

### Task 8: `ScheduledScan` module

**Files:**
- Create: `src/metatron/freshness/scheduled_scan.py`
- Create: `tests/unit/freshness/test_scheduled_scan.py`

- [ ] **Step 1: Write unit tests first.**
  Cases:
  - Happy path: two workspaces, stub `workspace_lister` returns both; target returns 3 ids for ws1 and 0 for ws2; 3 `enqueue_job` calls with correct `event_type="scheduled_scan"`, `target_kind`, `target_id`, `payload["older_than_iso"]`; `scheduled_scan_jobs_enqueued` counter += 3.
  - `workspace_lister` raises: return 0; `scheduled_scan_errors` counter += 1.
  - Per-workspace target raise: error swallowed; other workspaces still processed; counter += 1.
  - Empty workspaces: returns 0; no counter changes.

- [ ] **Step 2: Implement `ScheduledScan`** per the spec § "Scheduled-scan module".

- [ ] **Step 3: Lint + typecheck + test.**

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/freshness/scheduled_scan.py tests/unit/freshness/test_scheduled_scan.py
  git commit -m "feat(MTRNIX-316): ScheduledScan module — safety-net enqueue for stale records"
  ```

---

### Task 9: Worker wiring — heartbeat + reclaim + scheduled scan

**Files:**
- Modify: `src/metatron/memory/freshness/worker.py`
- Create: `tests/unit/memory/freshness/test_worker_reclaim_loop.py`

- [ ] **Step 1: Write unit tests first.**
  Mock `CoordinationStore` at the call-boundary; assert:
  - Startup path: `tick_heartbeat`, `reclaim_worker_orphans` for every worker in `list_processing_workers`, optional `drain_legacy_unprefixed` (when flag true).
  - Per-iteration: `tick_heartbeat` called; `list_processing_workers + reclaim_worker_orphans` called only every N iterations (N=3 in test).
  - Scheduled scan: `ScheduledScan.run` called on timer boundary (fake `time.monotonic`).
  - `complete_job` called in `_process_job` finally, both on success and on exception.
  - Graceful shutdown (CancelledError bubbled up to `main`): `release_worker` called.

- [ ] **Step 2: Modify `FreshnessWorker.__init__`.**
  Add kwargs: `worker_id`, `scheduled_scanners`, `heartbeat_ttl`, `reclaim_interval_iterations`, `scheduled_scan_interval_seconds`. Store on `self`. Initialise `self._iteration_count = 0` and `self._last_scan_monotonic = 0.0`.

- [ ] **Step 3: Modify `run_once`.**
  - At entry: `self._iteration_count += 1`; `await self._coord.tick_heartbeat(self._worker_id, self._heartbeat_ttl)` (swallow on exception, bump `reclaim_errors{stage="heartbeat"}`).
  - Every `self._reclaim_interval_iterations` iterations: `await self._reclaim_all_orphans()`.
  - If scheduled scans due: `await self._run_scheduled_scans()`.
  - Dequeue call: pass `worker_id=self._worker_id`.
  - In `_process_job` `finally`: after `save_machine_event(freshness_job_processed)`, `await self._coord.complete_job(self._worker_id, job)` (swallow on exception; log WARNING).

- [ ] **Step 4: Implement `_reclaim_all_orphans`.**
  Swallows all errors:
  ```python
  async def _reclaim_all_orphans(self) -> None:
      try:
          worker_ids = await self._coord.list_processing_workers()
      except Exception:
          metrics.reclaim_errors.labels(env=get_settings().env, stage="discover").inc()
          logger.warning("freshness.reclaim.discover_failed", exc_info=True)
          return
      logger.info("freshness.reclaim.discovered", worker_count=len(worker_ids))
      for wid in worker_ids:
          if wid == self._worker_id:
              continue  # never reclaim ourselves
          try:
              n = await self._coord.reclaim_worker_orphans(wid)
              if n:
                  logger.info("freshness.reclaim.jobs_recovered", dead_worker_id=wid, count=n)
          except Exception:
              metrics.reclaim_errors.labels(env=get_settings().env, stage="drain").inc()
              logger.warning("freshness.reclaim.drain_failed", dead_worker_id=wid, exc_info=True)
  ```

- [ ] **Step 5: Implement `_run_scheduled_scans`.**
  - Check `self._scheduled_scanners` list; for each, call `.run()` (method swallows its own errors); set `self._last_scan_monotonic = time.monotonic()`.

- [ ] **Step 6: Modify `_build_worker` + `main`.**
  - Build `worker_id = build_worker_id()`.
  - Wire one `ScheduledScan` for memory (pass `MemoryTarget` + coordination + a workspace-lister lambda that calls `PostgresStore.list_workspaces` + the memory settings for `stale_after_days` and `scan_batch_limit`).
  - Pass `worker_id` + `scheduled_scanners=[...]` + the four timing knobs from settings into the `FreshnessWorker` ctor.
  - In `main`, before entering `_run_loop`: `await coord.tick_heartbeat(worker_id, ...)`; `await worker._reclaim_all_orphans()`; if `settings.freshness_drain_legacy_at_startup`: `await coord.drain_legacy_unprefixed()`.
  - Register a signal-agnostic graceful-shutdown path: wrap `_run_loop` in a try / `asyncio.CancelledError` handler; `await coord.release_worker(worker_id)` in `finally`.

- [ ] **Step 7: Lint + typecheck + test.**

- [ ] **Step 8: Commit.**
  ```
  git add src/metatron/memory/freshness/worker.py tests/unit/memory/freshness/test_worker_reclaim_loop.py
  git commit -m "feat(MTRNIX-316): worker — heartbeat + reclaim pass + scheduled scan wiring"
  ```

**Acceptance:** Unit tests green. Manual smoke run: `METATRON_FRESHNESS_ENABLED=true python -m metatron.memory.freshness` — log output shows `worker_id_assigned`, `heartbeat_tick`, `reclaim.start`, `scheduled_scan.start`.

---

### Task 10: Integration — SIGKILL mid-batch reclaim

**Files:**
- Create: `tests/integration/memory/freshness/test_reclaim_sigkill.py`

- [ ] **Step 1: Test scaffolding.**
  - Reuse conftest fixtures for PG/Redis/Qdrant connections.
  - Helper `_spawn_worker(worker_id: str, env_overrides: dict[str, str]) -> subprocess.Popen`:
    spawns `[sys.executable, "-m", "metatron.memory.freshness"]` with `METATRON_FRESHNESS_TEST_WORKER_ID=<id>` + `METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS=<ms>` in env.

- [ ] **Step 2: Add a test-only knob to the worker.**
  Inside `_process_job`, if `METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS` is set, `await asyncio.sleep(int(...) / 1000)` BEFORE the pipeline calls. This widens the window between LMOVE and LREM deterministically. Guard with `if os.environ.get(...)`.

- [ ] **Step 3: Write the test.**
  ```python
  @pytest.mark.integration
  async def test_reclaim_after_sigkill_recovers_all_jobs(...):
      workspace = f"fresh-it-{uuid4().hex[:8]}"
      # Seed N=5 memory records + enqueue jobs
      # ...
      worker_a = _spawn_worker("worker-a", env={"METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS": "3000"})
      # Poll processing-list LLEN until it shows >=1 item (or 5s timeout)
      await _wait_for_processing_list("worker-a", min_items=1, timeout_s=5)
      # Kill
      os.kill(worker_a.pid, signal.SIGKILL)
      worker_a.wait(timeout=5)
      # Count total jobs still alive (queue + processing)
      total = await coord.queue_depth(workspace) + await _llen_processing("worker-a")
      assert total == 5
      # Spawn worker B (no sleep)
      worker_b = _spawn_worker("worker-b", env={})
      try:
          # Wait for PG to show all 5 records processed
          await _wait_for_events(workspace, event_type="freshness_job_processed",
                                  expected_count=5, timeout_s=30)
          # Processing list for dead worker should be empty now
          assert await _llen_processing("worker-a") == 0
      finally:
          worker_b.send_signal(signal.SIGTERM)
          worker_b.wait(timeout=5)
  ```

- [ ] **Step 4: Cleanup path (both on success and failure).**
  DELETE memory_records / review_entries / machine_events for workspace; DEL all `freshness:*` keys under the current env; dispose engine + redis + qdrant clients.

- [ ] **Step 5: Lint + typecheck + test-all.**

- [ ] **Step 6: Commit.**
  ```
  git add tests/integration/memory/freshness/test_reclaim_sigkill.py src/metatron/memory/freshness/worker.py
  git commit -m "test(MTRNIX-316): integration — SIGKILL mid-batch + second worker reclaims"
  ```

**Acceptance:** Test passes under `make test-all`. The AC gate for the ticket.

---

### Task 11: Integration — scheduled scan enqueues stale

**Files:**
- Create: `tests/integration/memory/freshness/test_scheduled_scan_enqueues_stale.py`

- [ ] **Step 1: Seed three memory records** with `updated_at = now - (stale_after_days + 5) days`, ACTIVE status; one control record with `updated_at = now`; all under a single workspace.

- [ ] **Step 2: Instantiate a `ScheduledScan`** with a stubbed `workspace_lister` that returns just this workspace, `stale_after_days=1` (to be strictly older than the seeded date — adjust accordingly).

- [ ] **Step 3: Call `scan.run()`; assert 3 jobs enqueued** (the three stale ones); control record NOT enqueued.

- [ ] **Step 4: Spawn a worker (same pattern as Task 10)**; wait for PG to show the 3 records transitioned to `STALE` by the Monitor stage.

- [ ] **Step 5: Cleanup + commit.**
  ```
  git commit -m "test(MTRNIX-316): integration — scheduled scan rescues stale records without write event"
  ```

---

### Task 12: Integration — env-prefix isolation

**Files:**
- Create: `tests/integration/memory/freshness/test_env_prefix_isolation.py`

- [ ] **Step 1: Enqueue one job** using a `CoordinationStore` wired to `METATRON_ENV=staging`.
- [ ] **Step 2: Spawn a worker** with `METATRON_ENV=development`; `METATRON_FRESHNESS_TEST_WORKER_ID=w-dev`.
- [ ] **Step 3: Wait 5s**, then assert:
  - No `freshness_job_received` MachineEvent for the seeded workspace.
  - The staging queue still holds the job (unprocessed).
- [ ] **Step 4: Spawn a second worker** with `METATRON_ENV=staging`; assert the job gets processed.
- [ ] **Step 5: Cleanup + commit.**
  ```
  git commit -m "test(MTRNIX-316): integration — env-prefixed keys isolate environments"
  ```

---

### Task 13: Docs — CLAUDE.md updates

**Files:**
- Modify: `src/metatron/memory/.claude/CLAUDE.md`
- Modify: `src/metatron/storage/.claude/claude.md`
- Modify: `docs/MEMORY_MCP_FOLLOWUPS.md`

- [ ] **Step 1: Memory module.**
  Add a bullet under `freshness/worker.py`:
  "Processing-list reclaim + periodic safety-net scheduled scan (MTRNIX-316). Each worker maintains `freshness:{env}:processing:{worker_id}` and `freshness:{env}:heartbeat:{worker_id}`. Orphaned processing lists (expired heartbeat) are drained back to the main queue by any live worker on startup + every `METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS` iterations."
  Add a bullet under `freshness/target_memory.py`:
  "`list_stale_candidates(ws, older_than, limit)` — MTRNIX-316: delegates to `MemoryPostgresStore.list_stale_candidates` for the scheduled-scan rescue path."

- [ ] **Step 2: Storage module.**
  Under `redis.py`:
  "`lmove_rightleft(src, dst)`, `peek_tail(key)`, `lrem(key, value, count)` — primitives for the freshness processing-list reclaim pattern (MTRNIX-316). Requires Redis >= 6.2."
  Under `memory_postgres.py`:
  "`list_stale_candidates(workspace_id, older_than, limit)` — returns ids of non-terminal-status records with `updated_at < older_than`, used by the scheduled-scan safety net (MTRNIX-316)."

- [ ] **Step 3: Follow-ups doc.**
  Add a new section:
  "## KB scheduled scan (MTRNIX-316 follow-up). `RawDocumentTarget.list_stale_candidates` defaults to empty. Implement via `raw_documents` with `last_freshness_run_at IS NULL OR < :older_than` and wire a second `ScheduledScan` instance in `_build_worker`. Low priority — producer-triggered scans already cover the KB hot path."

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/memory/.claude/CLAUDE.md src/metatron/storage/.claude/claude.md docs/MEMORY_MCP_FOLLOWUPS.md
  git commit -m "docs(MTRNIX-316): CLAUDE.md + follow-ups — reclaim + scheduled scan"
  ```

---

### Task 14: CHANGELOG + docker-compose note

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docker-compose.yml` (one comment line)

- [ ] **Step 1: CHANGELOG entry.**
  ```
  - **Freshness worker:** processing-list reclaim + scheduled-scan safety net +
    env-prefixed Redis keys close the Phase A pre-prod gaps (MTRNIX-316).
    Requires Redis >= 6.2 for `LMOVE`. Dequeue no longer loses jobs on worker
    SIGKILL mid-batch; a live worker drains any orphaned processing list on
    startup + every ~60s. A periodic scan rescues memory records that never
    received a write-triggered freshness event. Every freshness Redis key is
    now namespaced by `METATRON_ENV`. Five new Prometheus counters:
    `freshness_orphans_reclaimed_total`, `freshness_reclaim_errors_total`,
    `freshness_scheduled_scan_jobs_enqueued_total`,
    `freshness_scheduled_scan_errors_total`, `freshness_legacy_keys_drained_total`.
  ```

- [ ] **Step 2: docker-compose.yml.**
  Add a comment next to the redis service: `# Redis >= 6.2 required for LMOVE (MTRNIX-316)`. Confirm pinned image `redis:7-alpine` satisfies this; no version bump needed.

- [ ] **Step 3: Commit.**
  ```
  git add CHANGELOG.md docker-compose.yml
  git commit -m "docs(MTRNIX-316): CHANGELOG + docker-compose Redis version note"
  ```

---

### Task 15: Final verification + PR

- [ ] **Step 1: Full test matrix.**
  - `make lint`
  - `make typecheck`
  - `make test`
  - `make test-all` (integration suite)

- [ ] **Step 2: Grep guardrails.**
  - `grep -rn "rpop_batch" src/metatron/` → no active prod call-site in freshness/.
  - `grep -rn "freshness:queue:" src/` → only inside `queue_key_for` (the one key helper).
  - `grep -rn "worker_id" src/metatron/freshness/ src/metatron/memory/freshness/` → present in coordination + worker.
  - `grep -rn "import metatron.agent\|import metatron.channels\|api.routes.chat\|api.routes.finops" src/metatron/freshness/ src/metatron/memory/freshness/` → empty.
  - `grep -rn "METATRON_FRESHNESS_ENV" src/` → empty (we do NOT invent a new var).

- [ ] **Step 3: Regression matrix.**
  - `make test tests/unit/freshness/`
  - `make test tests/unit/memory/freshness/`
  - `make test tests/unit/storage/`
  - `make test tests/unit/core/`
  - `make test tests/integration/memory/freshness/`

- [ ] **Step 4: Manual smoke.**
  - `METATRON_FRESHNESS_ENABLED=true python -m metatron.memory.freshness` for 60s against a dev Redis + PG: expect log lines for `worker_id_assigned`, `heartbeat_tick` every 2s, `reclaim.start` once at boot, scheduled-scan timer logged as pending until it fires.

- [ ] **Step 5: Open PR.**
  Title: `feat(MTRNIX-316): freshness queue reliability — processing-list reclaim + scheduled scan`
  Body: Summary (1 paragraph), Scope (bullet list of touched files — files in File Map above), Validation (commands + AC checklist — all 12 spec items), Enterprise courtesy (five new Prometheus counters), Redis version requirement note. No Co-Authored-By, no Claude Code badge.

**Acceptance:** CI green; AC items 1-12 from the spec checklist all verifiable in code.

---

## Risks watchlist

- **Protocol default body portability.** Python's `typing.Protocol` does not always accept method bodies under mypy strict; fallback is to add implementations on both concrete classes (`MemoryTarget`, `RawDocumentTarget`) explicitly. Keep the default empty `return []` on `RawDocumentTarget` if Protocol-default doesn't work. Settled in Task 7 Step 2.
- **Test-only env-knob leaking into production.** `METATRON_FRESHNESS_TEST_WORKER_ID` and `METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS` are honoured unconditionally. Document them in the module docstring + CLAUDE.md as "integration-test hooks; do not set in production deployments".
- **Deprecation shim for `dequeue_batch` without `worker_id`.** Keep the shim narrow: just tests. Add a TODO to remove in a follow-up PR once all tests migrate. Do NOT delete in this ticket (breaks Phase A unit tests).
- **Integration test flakiness.** Poll loops with explicit timeouts (not `time.sleep`). If CI is slow, bump the default poll budget via `METATRON_FRESHNESS_TEST_PROCESS_SLEEP_MS=5000` in the test harness.
- **Docker-compose Redis version drift.** The pinned image is `redis:7-alpine`. If a future change downgrades below 6.2 somebody loses `LMOVE` at runtime. Spec + CHANGELOG + compose comment + release notes all call it out. Consider adding an integration-smoke that asserts `await redis._client.info("server")["redis_version"] >= "6.2"` (deferred to follow-up; low priority).
- **Worker hostname collision in k8s.** k8s assigns pod-stable hostnames; collision after restart is rare and mitigated by uuid suffix. No action.
- **Reclaim lock TTL.** 30s is plenty for draining a typical processing list (≤20 items × 2ms RTT). If stuck, TTL expires → next iteration retries. Logged at WARNING via the outer swallow.

---

## Coordination points

- **`core/interfaces.py`** unchanged.
- **`core/events.py`** unchanged.
- **`core/models.py`** unchanged. `FreshnessJob.event_type="scheduled_scan"` is already reserved.
- **`FreshnessTarget` Protocol** — one new method, backwards-compatible default. KB adapter (`RawDocumentTarget`) gets the default `return []` (explicitly or via Protocol default) — KB tests unchanged.
- **Enterprise repo** — no coordination required for functionality. Courtesy in the PR body: five new Prometheus counters for enterprise Grafana dashboards. `MachineEvent` shape unchanged.
- **Ops runbook** — add notes (informal, in the PR body):
  - `freshness_orphans_reclaimed_total > 0` is informational during worker restarts; not a page.
  - `freshness_reclaim_errors_total` rate > 0 for 10 min → check Redis health.
  - `freshness_scheduled_scan_errors_total` rate > 0 → check PG.
  - During env-prefix rollout: set `METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP=true` for ONE deploy, then unset.
- **Deployment** — Redis >= 6.2 is a hard requirement; current pinned image (`redis:7-alpine`) is fine. Document in PR body.
- **`docs/MEMORY_MCP_FOLLOWUPS.md`** — gains one "KB scheduled scan" entry.
