# Memory freshness worker — Qdrant status payload sync — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** close the worker-side drift between `memory_records.status` (PG) and the `mem_agent_memory_{workspace_id}` Qdrant collection's `status` payload by making every freshness-pipeline lifecycle transition best-effort sync the Qdrant payload via `MemoryTarget.sync_downstream_stores` (currently a no-op). Add one Prometheus counter `freshness_qdrant_sync_failed_total` for observability. Backfill script stays as the long-tail safety net.

**Architecture:** Option A — reuse the existing `FreshnessTarget.sync_downstream_stores` protocol hook from MTRNIX-313. Memory adapter's no-op implementation becomes a real `qdrant.update_payload(record_id, {"status": status.value})`, best-effort. Two missing call sites (`Curator.run`, `apply_decision.apply_decision`) gain the hook invocation. `FreshnessMonitor.run` already calls it. `Reconciler` doesn't mutate `memory_records.status` (verified) — left unchanged.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async (asyncpg), `redis.asyncio`, `AsyncQdrantClient`, `prometheus_client` (optional dep), structlog, pytest (`asyncio_mode = "auto"`).

**Jira:** MTRNIX-322
**Depends on:** MTRNIX-304 (merged), MTRNIX-313 (merged), MTRNIX-314 (merged), MTRNIX-319 (merged, PR #89).
**Spec:** `docs/superpowers/specs/2026-04-24-memory-freshness-qdrant-status-sync-design.md`
**Branch:** `feature/MTRNIX-322` (already checked out).

---

## Layer Boundary Summary

| File | Layer | Allowed imports |
|---|---|---|
| `src/metatron/freshness/metrics.py` (extend) | L2 | `prometheus_client` (optional) |
| `src/metatron/memory/freshness/metrics.py` (extend re-export) | L3 | `metatron.freshness.metrics` |
| `src/metatron/memory/freshness/target_memory.py` (extend) | L3 | `metatron.freshness.metrics`, `metatron.freshness.targets`, `storage.memory_postgres`, `storage.memory_qdrant` |
| `src/metatron/freshness/stages/curator.py` (extend) | L2 | `metatron.freshness.targets`, `metatron.core.*`, `storage.freshness_pg` |
| `src/metatron/freshness/apply_decision.py` (extend) | L2 | `metatron.freshness.targets`, `metatron.core.*`, `storage.freshness_pg` |

**Not touched:** `core/interfaces.py`, `core/events.py`, `core/models.py`, `storage/memory_postgres.py`, `storage/memory_qdrant.py`, `freshness/targets.py`, `freshness/stages/linker.py`, `freshness/stages/reconciler.py`, `freshness/stages/monitor.py`, `freshness/decision_engine.py`, `memory/service.py`, `memory/search.py`, `mcp/tools/*`, `ingestion/freshness/*`, `api/*`.

**No upward imports.** Memory adapter (L3) imports shared freshness metrics (L2); shared freshness stages (L2) import `metatron.freshness.targets` (L2) — no new dependencies.

---

## Config Vars

**None added.** No new env flags.

---

## Event Constants

**None added.** `core/events.py` unchanged.

---

## Backward Compatibility Guarantee

- `MemoryTarget.sync_downstream_stores` signature unchanged (MTRNIX-313 already defined it). Implementation changes from no-op to real Qdrant write.
- `FreshnessTarget` Protocol unchanged.
- `update_lifecycle` semantics unchanged. Transaction semantics unchanged (Qdrant write is outside any PG transaction).
- Phase A (MTRNIX-304) + Phase B (MTRNIX-313) + MTRNIX-314 tests stay green.
- Existing behaviour WITHOUT this fix: Qdrant payload stale after worker transitions (the bug). The fix is a silent improvement; no API callers change.
- Prometheus metric is additive; scrapers tolerate new series.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/metatron/freshness/metrics.py` | Add `qdrant_sync_failed: Counter` guarded by the existing `try/except ImportError`. Add to `__all__`. |
| Modify | `src/metatron/memory/freshness/metrics.py` | Re-export `qdrant_sync_failed` from the shared metrics module. |
| Modify | `src/metatron/memory/freshness/target_memory.py` | Replace `sync_downstream_stores` no-op with a best-effort Qdrant `update_payload({"status": status.value})`. Import `metrics` lazily inside the method body (or at module top) to avoid cycles. |
| Modify | `src/metatron/freshness/stages/curator.py` | After `update_lifecycle(..., status=ACTIVE, ...)` and before `save_machine_event`, call `self._target.sync_downstream_stores(..., status=LifecycleStatus.ACTIVE, freshness_score=record.freshness_score or 0.5)`. |
| Modify | `src/metatron/freshness/apply_decision.py` | In the `if decision.action == "mark_stale":` branch, after `await target.update_lifecycle(...)`, call `await target.sync_downstream_stores(workspace_id, record.target_id, status=LifecycleStatus.STALE, freshness_score=0.25)`. |
| Create | `tests/unit/memory/freshness/test_target_memory_sync_downstream.py` | Unit tests for `MemoryTarget.sync_downstream_stores`: success path writes payload; failure swallows + logs + counter increments; `freshness_score` is accepted but not written. |
| Create | `tests/unit/freshness/test_curator_qdrant_sync.py` | Curator CANDIDATE → ACTIVE transition calls `sync_downstream_stores`; Qdrant failure does not abort PG transition. |
| Create | `tests/unit/freshness/test_apply_decision_qdrant_sync.py` | `apply_decision` with `mark_stale` calls `sync_downstream_stores`; tag-only branch does NOT call it; Qdrant failure does not abort. |
| Create | `tests/unit/freshness/test_monitor_qdrant_sync_memory_target.py` | Regression: `FreshnessMonitor.run` against a real `MemoryTarget` with a mock `MemoryQdrantStore` — assert `update_payload` called with correct `{"status": ...}` on all three rule branches. |
| Create | `tests/integration/memory/freshness/test_qdrant_status_sync_live.py` | Integration: end-to-end worker run against live PG + Qdrant + Redis. Seed a memory record with `valid_until < now`, run worker, assert `MemoryQdrantStore.search(status_exclude=["archived"])` does NOT return the record and PG status is ARCHIVED — all without running the backfill script. |
| Create | `tests/integration/memory/freshness/test_qdrant_sync_resilience.py` | Integration: monkey-patch `MemoryQdrantStore.update_payload` to raise; run worker; assert PG transitions land, MachineEvents land, counter incremented. Worker loop does NOT abort. |
| Modify | `docs/MEMORY_MCP_FOLLOWUPS.md` | Remove item #4 section entirely. Remove the "#4 has a real correctness impact today …" bullet from the trailing "Open question" section. Leave items 1-3 untouched. |
| Modify | `src/metatron/memory/.claude/CLAUDE.md` | Update the `freshness/target_memory.py` description: "`sync_downstream_stores` mirrors the PG `status` into the memory Qdrant collection's payload best-effort (MTRNIX-322)." |
| Modify | `src/metatron/storage/.claude/CLAUDE.md` | No code change but add a one-liner under `memory_qdrant.py::update_payload`: "Called by `MemoryTarget.sync_downstream_stores` after every worker-driven lifecycle transition (MTRNIX-322)." |
| Modify | `CHANGELOG.md` | One-line entry under unreleased: "feat(freshness): worker-driven lifecycle transitions now sync `status` payload to the memory Qdrant collection best-effort; adds `freshness_qdrant_sync_failed_total` counter (MTRNIX-322)." |

Total: 5 modified code files + 2 modified docs + 1 CHANGELOG + 4 new test files + 2 integration tests.

---

## Ordered Tasks

Execute in order. After **every** task, run `make lint`, `make typecheck`, `make test` as three separate commands (never chain with `;` or `&&` per the user's global rule).

---

### Task 1: Add the Prometheus counter

**Files:**
- Modify: `src/metatron/freshness/metrics.py`
- Modify: `src/metatron/memory/freshness/metrics.py`

- [ ] **Step 1: Add the module-level `qdrant_sync_failed` declaration.**
  Insert `qdrant_sync_failed: Any` near the other counter declarations (alphabetically between `queue_depth_gauge` and `stage_duration`, or at the end of the list — match existing order).

- [ ] **Step 2: Add the real Counter inside the try/except.**
  Inside the `try:` block, after the `worker_errors = Counter(...)` definition, add:
  ```python
  qdrant_sync_failed = Counter(
      "freshness_qdrant_sync_failed_total",
      "Best-effort Qdrant payload sync failures from the freshness pipeline",
      ["target_kind", "stage"],
  )
  ```

- [ ] **Step 3: Add the `_NoopMetric()` fallback.**
  Inside the `except ImportError:` block, add `qdrant_sync_failed = _NoopMetric()`.

- [ ] **Step 4: Add to `__all__`.**
  Insert `"qdrant_sync_failed",` alphabetically (between `"jobs_total"` and `"queue_depth_gauge"`).

- [ ] **Step 5: Re-export from the memory shim.**
  In `src/metatron/memory/freshness/metrics.py`, add `qdrant_sync_failed` to the `from metatron.freshness.metrics import (...)` statement and the `__all__` list.

- [ ] **Step 6: Write a quick smoke test.**
  In a temporary test (can live in `test_target_memory_sync_downstream.py` from Task 3) confirm `from metatron.freshness.metrics import qdrant_sync_failed` succeeds and `.labels(target_kind="memory_record", stage="sync_downstream").inc()` does not raise, under both branches (with/without prometheus_client — the ImportError branch is exercised in CI when the optional dep is absent; don't add a separate uninstall dance).

- [ ] **Step 7: Lint + typecheck + test.** Three separate commands.

- [ ] **Step 8: Commit.**
  ```
  git add src/metatron/freshness/metrics.py src/metatron/memory/freshness/metrics.py
  git commit -m "feat(MTRNIX-322): add freshness_qdrant_sync_failed_total counter"
  ```

**Acceptance:** New counter importable from both `metatron.freshness.metrics` and the memory shim; no-op fallback present; CI green.

---

### Task 2: Implement `MemoryTarget.sync_downstream_stores`

**Files:**
- Modify: `src/metatron/memory/freshness/target_memory.py`
- Create: `tests/unit/memory/freshness/test_target_memory_sync_downstream.py`

- [ ] **Step 1: Write the unit test first (TDD).**
  Three cases:
  - Happy path: `MemoryTarget` with mocked Qdrant factory; call `sync_downstream_stores(ws, "mem_1", status=LifecycleStatus.STALE, freshness_score=0.25)`; assert `qdrant.update_payload` called with `("mem_1", {"status": "stale"})` (only `status`, no `freshness_score`).
  - Failure path: mocked `update_payload` raises `RuntimeError("qdrant down")`; assert no exception propagates; assert `logger.warning` called once with `event="freshness.memory_target.qdrant_payload_sync_failed"`.
  - Counter path: patch `metatron.freshness.metrics.qdrant_sync_failed`; assert `.labels(target_kind="memory_record", stage="sync_downstream").inc()` called exactly once on the failure path, zero times on the happy path.

- [ ] **Step 2: Import the metrics module.**
  At the top of `target_memory.py`, add:
  ```python
  from metatron.freshness import metrics
  ```
  (Not inside `TYPE_CHECKING` — we need it at runtime.)

- [ ] **Step 3: Replace the `sync_downstream_stores` body.**
  Current body: `# Memory does not mirror status ... return None`. Replace with the adapter implementation from the spec:
  ```python
  async def sync_downstream_stores(
      self,
      workspace_id: str,
      target_id: str,
      *,
      status: LifecycleStatus,
      freshness_score: float,
  ) -> None:
      """Mirror ``memory_records.status`` into the Qdrant payload.

      Best-effort — Qdrant is a derived store. Failures are logged at
      WARNING, counted on ``freshness_qdrant_sync_failed_total``, and
      never propagate. PG remains the source of truth; the backfill
      script at ``scripts/backfill_memory_qdrant_status_payload.py`` is
      the long-tail safety net for persistent drift.

      ``freshness_score`` is accepted for interface symmetry with the
      KB adapter but not written — memory Qdrant points do not carry a
      ``freshness_score`` payload field (MTRNIX-322).
      """
      del freshness_score  # documented: not persisted for memory target
      try:
          qdrant = await self._resolve_qdrant(workspace_id)
          await qdrant.update_payload(target_id, {"status": status.value})
      except Exception:
          logger.warning(
              "freshness.memory_target.qdrant_payload_sync_failed",
              workspace_id=workspace_id,
              target_id=target_id,
              status=status.value,
              exc_info=True,
          )
          try:
              metrics.qdrant_sync_failed.labels(
                  target_kind="memory_record",
                  stage="sync_downstream",
              ).inc()
          except Exception:  # noqa: BLE001 — metrics must never bite
              pass
  ```

- [ ] **Step 4: Lint + typecheck + test.**

- [ ] **Step 5: Commit.**
  ```
  git add src/metatron/memory/freshness/target_memory.py tests/unit/memory/freshness/test_target_memory_sync_downstream.py
  git commit -m "feat(MTRNIX-322): MemoryTarget.sync_downstream_stores writes Qdrant status payload"
  ```

**Acceptance:** 3 unit tests green. `MemoryMonitor.run` (already invokes the hook) now actually writes to Qdrant.

---

### Task 3: Regression test — Monitor triggers Qdrant sync

**Files:**
- Create: `tests/unit/freshness/test_monitor_qdrant_sync_memory_target.py`

- [ ] **Step 1: Test setup.**
  Spin up a real `MemoryTarget` (not a mock), with mocked `MemoryPostgresStore` + `MemoryQdrantStore` (so we see the exact call into Qdrant).

- [ ] **Step 2: Three test cases — one per Monitor rule branch.**
  - `valid_until < now` → ARCHIVED. Assert `qdrant.update_payload` called with `{"status": "archived"}`.
  - `superseded_by` set → SUPERSEDED. Assert `{"status": "superseded"}`.
  - `updated_at < now - stale_after_days` → STALE. Assert `{"status": "stale"}`.

- [ ] **Step 3: Assert the MachineEvent was still saved** (regression against accidentally skipping it).

- [ ] **Step 4: Lint + typecheck + test.**

- [ ] **Step 5: Commit.**
  ```
  git add tests/unit/freshness/test_monitor_qdrant_sync_memory_target.py
  git commit -m "test(MTRNIX-322): Monitor transitions write Qdrant status payload"
  ```

**Acceptance:** 3 tests green. The hook invocation wiring from MTRNIX-313 is now covered against the real adapter.

---

### Task 4: Curator — call `sync_downstream_stores`

**Files:**
- Modify: `src/metatron/freshness/stages/curator.py`
- Create: `tests/unit/freshness/test_curator_qdrant_sync.py`

- [ ] **Step 1: Write the unit test first.**
  Four cases:
  - Happy path: seed a mock target with a CANDIDATE record (`evidence_count=1`), mock Qdrant via the target's `sync_downstream_stores`; call `Curator.run`; assert the hook was called with `status=LifecycleStatus.ACTIVE` and the record's `freshness_score` (or `0.5` fallback).
  - Qdrant-failure path: mock `sync_downstream_stores` to swallow and simulate counter increment (delegated to the adapter); assert `Curator.run` still returns `LifecycleStatus.ACTIVE` and the MachineEvent was still saved.
  - No-transition path: status=ACTIVE; Curator short-circuits; `sync_downstream_stores` NOT called.
  - Evidence-insufficient path: status=CANDIDATE, evidence_count=0; short-circuits; `sync_downstream_stores` NOT called.

- [ ] **Step 2: Modify `Curator.run`.**
  Inside the `try:` block, after the existing `await self._target.update_lifecycle(...)` call (which writes status=ACTIVE + append_tag) and BEFORE `await self._freshness_store.save_machine_event(...)`, insert:
  ```python
  await self._target.sync_downstream_stores(
      workspace_id,
      target_id,
      status=LifecycleStatus.ACTIVE,
      freshness_score=record.freshness_score or 0.5,
  )
  ```
  (Keep it inside the `try/finally` so the lock is released correctly if it unexpectedly raises — though the adapter contract says it never does; belt + suspenders.)

- [ ] **Step 3: Lint + typecheck + test.**

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/freshness/stages/curator.py tests/unit/freshness/test_curator_qdrant_sync.py
  git commit -m "feat(MTRNIX-322): Curator promotes CANDIDATE → ACTIVE with Qdrant payload sync"
  ```

**Acceptance:** 4 unit tests green. Curator's PG promotion now pairs with Qdrant sync.

---

### Task 5: `apply_decision` — call `sync_downstream_stores` on `mark_stale`

**Files:**
- Modify: `src/metatron/freshness/apply_decision.py`
- Create: `tests/unit/freshness/test_apply_decision_qdrant_sync.py`

- [ ] **Step 1: Write the unit test first.**
  Four cases:
  - `mark_stale` above threshold: `apply_decision` writes `status=STALE` AND calls `sync_downstream_stores(..., status=STALE, freshness_score=0.25)`. Returns `{"applied": True, ...}`.
  - Tag-only above threshold (action != "mark_stale" but tags present): calls `update_lifecycle(append_tag=...)` only; does NOT call `sync_downstream_stores`.
  - Below threshold: creates `ReviewEntry`; does NOT call `sync_downstream_stores` or `update_lifecycle`.
  - Qdrant failure on `sync_downstream_stores` (mocked to swallow + counter): `apply_decision` still returns `{"applied": True, ...}` without propagating.

- [ ] **Step 2: Modify `apply_decision`.**
  In the `if decision.action == "mark_stale":` branch, after
  ```python
  await target.update_lifecycle(
      workspace_id,
      record.target_id,
      status=LifecycleStatus.STALE,
      freshness_score=0.25,
      append_tag=joined_tag,
  )
  ```
  append:
  ```python
  await target.sync_downstream_stores(
      workspace_id,
      record.target_id,
      status=LifecycleStatus.STALE,
      freshness_score=0.25,
  )
  ```

- [ ] **Step 3: Lint + typecheck + test.**

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/freshness/apply_decision.py tests/unit/freshness/test_apply_decision_qdrant_sync.py
  git commit -m "feat(MTRNIX-322): apply_decision mark_stale path syncs Qdrant payload"
  ```

**Acceptance:** 4 unit tests green. The DecisionEngine auto-apply path now pairs STALE transition with Qdrant sync.

---

### Task 6: Integration — live end-to-end AC scenario

**Files:**
- Create: `tests/integration/memory/freshness/test_qdrant_status_sync_live.py`

- [ ] **Step 1: Seed fixture.**
  Reuse the existing memory integration fixture set (`tests/integration/memory/conftest.py`) — live PG engine, live Qdrant client, live Redis. Create a workspace, seed one `MemoryRecord` with `valid_until=datetime.now(UTC) - timedelta(days=1)` via `MemoryService.save` (this routes through the normal upsert, so Qdrant point exists with `status="active"`).

- [ ] **Step 2: Run one worker iteration.**
  Build the `FreshnessWorker` via the same helper the worker module uses (or a test-only builder). Enqueue a job via `CoordinationStore.enqueue`. Call `worker.run_once(1)`.

- [ ] **Step 3: Assert PG.**
  `memory_records.status == 'archived'` (because `valid_until < now` → Monitor → ARCHIVED).

- [ ] **Step 4: Assert Qdrant.**
  `MemoryQdrantStore.search(query="<record content>", agent_id=..., top_k=5, status_exclude=["archived"])` returns EMPTY. A second call with `status_exclude=None` returns the record (sanity — it's still in Qdrant, just filtered). The `status` payload on the point is `"archived"` (retrievable via `scroll` for sanity, optional).

- [ ] **Step 5: Reproduce the original MTRNIX-319 §1 scenario at MCP layer.**
  Call the MCP tool `metatron_memory_search(query=..., status=["active"])` (invoke the tool function directly, wrapping the service); assert EMPTY return set. This is the exact regression gate.

- [ ] **Step 6: Lint + typecheck + test-all.**

- [ ] **Step 7: Commit.**
  ```
  git add tests/integration/memory/freshness/test_qdrant_status_sync_live.py
  git commit -m "test(MTRNIX-322): integration — worker lifecycle transition syncs Qdrant status"
  ```

**Acceptance:** Integration test green against live PG + Qdrant + Redis. MTRNIX-319 §1 reproduction is now a pass gate.

---

### Task 7: Integration — Qdrant outage resilience

**Files:**
- Create: `tests/integration/memory/freshness/test_qdrant_sync_resilience.py`

- [ ] **Step 1: Seed fixture** identically to Task 6.

- [ ] **Step 2: Patch `MemoryQdrantStore.update_payload` to raise.**
  Use `monkeypatch.setattr` on the class (not the instance — the adapter resolves fresh stores via the factory). Patch it to `raise RuntimeError("qdrant down")` on every call.

- [ ] **Step 3: Run the worker iteration.**

- [ ] **Step 4: Assertions.**
  - PG `memory_records.status == 'archived'` (transition committed despite Qdrant failure).
  - `machine_events` has the `freshness_stage_completed` row for the Monitor step.
  - Counter `freshness_qdrant_sync_failed_total{target_kind="memory_record",stage="sync_downstream"}` is >= 1. (Access via `prometheus_client.REGISTRY.get_sample_value` or the noop `_value` attribute in the stub — test uses the real counter since the CI env has the dep.)
  - Worker loop did NOT raise (assert `run_once` returned normally).
  - MCP search WITH default `status=["active"]` filter still leaks the record (because Qdrant payload is stale — the intended behaviour: PG correct, Qdrant stale, drift present but observable).
  - Running `scripts/backfill_memory_qdrant_status_payload.py` (or equivalent inline code) on the workspace fixes the drift; rerun MCP search — record now excluded.

- [ ] **Step 5: Lint + typecheck + test-all.**

- [ ] **Step 6: Commit.**
  ```
  git add tests/integration/memory/freshness/test_qdrant_sync_resilience.py
  git commit -m "test(MTRNIX-322): integration — Qdrant outage doesn't abort worker PG transitions"
  ```

**Acceptance:** Integration test green. Graceful degradation verified.

---

### Task 8: Update `docs/MEMORY_MCP_FOLLOWUPS.md`

**Files:** `docs/MEMORY_MCP_FOLLOWUPS.md`

- [ ] **Step 1: Delete item #4 entirely** — remove the `## 4. Worker-driven proactive Qdrant status sync` heading and all its body lines up to (but not including) the next `## ...` heading.

- [ ] **Step 2: Delete the #4 bullet** from the trailing "## Open question — should any of these be filed as tickets now?" section:
  - Remove the line `- **#4** has a real correctness impact today ...` entirely.
  - Update the preamble from "The default answer is probably "yes for #4, maybe #1, not #2/#3":" to "The default answer is probably "maybe #1, not #2/#3":".

- [ ] **Step 3: No renumbering of items 1-3** — their `## 1.`, `## 2.`, `## 3.` headings stay.

- [ ] **Step 4: Commit.**
  ```
  git add docs/MEMORY_MCP_FOLLOWUPS.md
  git commit -m "docs(MTRNIX-322): remove resolved item #4 from memory MCP follow-ups"
  ```

**Acceptance:** The doc reads cleanly with #4 removed; #1-#3 intact.

---

### Task 9: Module-level CLAUDE.md updates

**Files:**
- Modify: `src/metatron/memory/.claude/CLAUDE.md`
- Modify: `src/metatron/storage/.claude/CLAUDE.md`

- [ ] **Step 1: Memory module docs.**
  Update the `freshness/target_memory.py` bullet list to add:
  ```
  - `sync_downstream_stores(ws, target_id, status, freshness_score)` — MTRNIX-322: best-effort writes `{"status": status.value}` to the per-workspace memory Qdrant point via `MemoryQdrantStore.update_payload`. Failures logged at WARNING, counted on `freshness_qdrant_sync_failed_total`, never propagate.
  ```

- [ ] **Step 2: Storage module docs.**
  Under `memory_qdrant.py`, append to the `update_payload` bullet: "Called by `MemoryTarget.sync_downstream_stores` on every worker-driven lifecycle transition (MTRNIX-322)."

- [ ] **Step 3: Commit.**
  ```
  git add src/metatron/memory/.claude/CLAUDE.md src/metatron/storage/.claude/CLAUDE.md
  git commit -m "docs(MTRNIX-322): module CLAUDE.md — memory target Qdrant sync"
  ```

**Acceptance:** Both docs reference the new hook behaviour.

---

### Task 10: CHANGELOG

**Files:** `CHANGELOG.md`

- [ ] **Step 1: Add entry** under the current unreleased section (or create the section if missing):
  ```
  - **Freshness worker:** memory lifecycle transitions (STALE / ACTIVE /
    SUPERSEDED / ARCHIVED) now propagate to the Qdrant `status` payload
    best-effort, closing the drift that leaked non-ACTIVE records through
    `memory_search` under the default `status=["active"]` filter. Adds
    Prometheus counter `freshness_qdrant_sync_failed_total` (MTRNIX-322).
  ```

- [ ] **Step 2: Commit.**
  ```
  git add CHANGELOG.md
  git commit -m "docs(MTRNIX-322): CHANGELOG entry"
  ```

---

### Task 11: Final verification + PR

- [ ] **Step 1: Full test matrix.**
  - `make lint`
  - `make typecheck`
  - `make test`
  - `make test-all` (integration suite)

- [ ] **Step 2: Grep guardrails.**
  - `grep -rn "update_payload" src/metatron/freshness/ src/metatron/memory/freshness/` → only `target_memory.py::sync_downstream_stores`.
  - `grep -rn "sync_downstream_stores" src/metatron/freshness/stages/ src/metatron/freshness/apply_decision.py` → hits in Monitor, Curator, apply_decision (3 call sites).
  - `grep -rn "workspace_id" src/metatron/memory/freshness/target_memory.py` → every Qdrant call has it.
  - `grep -rn "import metatron.agent\|import metatron.channels\|api.routes.chat\|api.routes.finops" src/metatron/freshness/ src/metatron/memory/freshness/` → empty.

- [ ] **Step 3: Phase A / B / MTRNIX-314 regression check.**
  - `make test tests/unit/freshness/` + `make test tests/unit/memory/freshness/` + `make test tests/unit/mcp/tools/` — zero regressions.

- [ ] **Step 4: Smoke-run the worker locally.**
  Seed a record with `valid_until < now` in a dev workspace; run `METATRON_FRESHNESS_ENABLED=true python -m metatron.memory.freshness` for one iteration; observe structured logs for the `freshness.memory_target.qdrant_payload_sync_failed` WARNING (it should NOT appear in the happy path); confirm the Qdrant payload via the admin CLI or an ad-hoc `MemoryQdrantStore.search` call.

- [ ] **Step 5: Open PR.**
  Title: `feat(MTRNIX-322): memory freshness worker syncs Qdrant status payload on lifecycle transitions`
  Body sections: Summary (1 paragraph), Scope (bullet list of touched files), Validation (commands + AC checklist), Enterprise courtesy (new Prometheus counter `freshness_qdrant_sync_failed_total`). No Co-Authored-By, no Claude Code badge.

**Acceptance:** Green CI; 7 open questions from spec closed in code; MTRNIX-319 §1 reproduction now a passing integration test.

---

## Risks watchlist

- **Metric cardinality** — labels bounded by design; monitor for unexpected `stage` values in production.
- **Phase B KB path untouched** — `RawDocumentTarget.sync_downstream_stores` is the reference pattern; we do not modify it. KB's Neo4j `set_raw_document_status` call is unrelated to this ticket.
- **Graph edges** — Reconciler writes `:ALIAS` graph edges best-effort (unchanged). Their sync is already best-effort; this ticket doesn't add graph work.
- **Worker process lifecycle** — no new threads, no new coroutines. Same bounded-loop shape.
- **Qdrant client pooling** — adapter re-resolves the per-workspace client on every call via the existing `_resolve_qdrant` factory; the factory caches. No new client lifecycle concerns.

---

## Coordination points

- **`core/interfaces.py`** unchanged.
- **`core/events.py`** unchanged.
- **`FreshnessTarget` Protocol** unchanged.
- **Enterprise repo** — courtesy mention in PR body: new Prometheus counter `freshness_qdrant_sync_failed_total`. Enterprise Grafana dashboards may want to add a panel; non-breaking.
- **`docs/MEMORY_MCP_FOLLOWUPS.md`** — item #4 removed. Items #1 / #2 / #3 untouched.
- **`scripts/backfill_memory_qdrant_status_payload.py`** — stays. Ops runbook addendum (informal): non-zero `freshness_qdrant_sync_failed_total` rate over a 1-hour window → run the backfill script on the affected workspaces.
```

