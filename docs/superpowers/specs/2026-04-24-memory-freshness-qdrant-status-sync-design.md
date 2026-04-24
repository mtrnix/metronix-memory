# Memory freshness worker — Qdrant status payload sync — Design

**Date:** 2026-04-24
**Jira:** MTRNIX-322 — Memory freshness worker — sync status payload to Qdrant on every lifecycle transition.
**Depends on:** MTRNIX-304 (Phase A), MTRNIX-313 (Phase B + shared `FreshnessTarget`), MTRNIX-314 (MCP status filter), MTRNIX-319 (atomicity fix in `resolve_review`).
**Parent epic:** MTRNIX-227 (Agent Memory System, WS1).
**Author:** Architect (agent-team)
**Status:** Draft — ready for implementation plan

## Goal

Close the worker-side drift between PostgreSQL `memory_records.status` and the
`mem_agent_memory_{workspace_id}` Qdrant collection's `status` payload. Today,
every freshness-pipeline lifecycle transition writes PG only; the Qdrant
payload catches up lazily on the next upsert. Result: records that the worker
transitions to `STALE` / `SUPERSEDED` / `ARCHIVED` still carry
`status="active"` in Qdrant and therefore leak through the MTRNIX-314
`must_not` exclusion filter (reproduced on live data in MTRNIX-319 §1).

The fix: reuse the existing `FreshnessTarget.sync_downstream_stores` hook
(already invoked by `FreshnessMonitor` after every STALE/SUPERSEDED/ARCHIVED
transition — MTRNIX-313) and:

1. Implement `MemoryTarget.sync_downstream_stores` to call
   `MemoryQdrantStore.update_payload(record_id, {"status": status.value})`
   best-effort. Today it is a deliberate no-op.
2. Add the same hook call in `Curator.run` (CANDIDATE → ACTIVE) and in
   `apply_decision.apply_decision` (when the decision writes `STALE` or when
   tag-only updates promote the record via other lifecycle paths).
3. Keep Reconciler unchanged (it writes `review_entries` only, never
   `memory_records.status`).
4. Expose a `freshness.qdrant_sync_failed` Prometheus counter so the drift
   rate is observable in production.

All changes are inside `src/metatron/freshness/` and
`src/metatron/memory/freshness/`. No schema migration. No flag. No MCP-layer
changes. No changes to `core/interfaces.py` or `core/events.py`.

## Non-goals

- KB raw_documents Qdrant sync — already done in MTRNIX-313 via
  `RawDocumentTarget.sync_downstream_stores`. Reference pattern only;
  do not touch.
- MCP-triggered transitions (`MemoryService.resolve_review`) — already
  sync Qdrant best-effort after PR #86 / #89. Not in scope.
- Backfill script lifecycle — `scripts/backfill_memory_qdrant_status_payload.py`
  stays as the operator safety net for historical drift and post-outage
  recovery. Not being removed.
- Pushing Qdrant writes into the PG transaction. Qdrant is a different
  data store; coupling its availability to PG transaction success is wrong
  (Qdrant outage would abort PG commits, breaking graceful degradation).
- 5-role RBAC, hard-delete, content-merge auto-merge — separate tickets.
- Search-time behaviour — MTRNIX-314's exclude-filter semantics handle the
  "missing `status` payload" case correctly; this ticket only improves
  steady-state consistency, not correctness under the existing filter.
- Metric for success (counter of successful syncs) — only the failure
  counter is specified; success is the default and already observable via
  `MachineEvent` rows.

## Constraints

- **Layer boundaries.** All new code sits at L2 (`src/metatron/freshness/`
  stages + `apply_decision`) or L3 (`src/metatron/memory/freshness/`
  adapter glue) or L1 (`src/metatron/storage/` no change required —
  `update_payload` already exists). No upward imports. No changes to
  `agent/`, `channels/`, `api/routes/chat.py`, `api/routes/finops.py`.
- **Workspace isolation.** `MemoryQdrantStore` is per-workspace already
  (collection name `mem_agent_memory_{workspace_id}`, resolved through
  the existing factory). Every new code path passes `workspace_id` down
  into `_resolve_qdrant(workspace_id)`.
- **Graceful degradation.** Qdrant failure NEVER aborts the PG transition
  or the worker loop. Match the `MemoryService.resolve_review` pattern:
  PG commit first, then `try: update_payload ... except Exception: log
  WARNING + increment counter`.
- **PG source of truth.** Qdrant derived store stays eventually consistent.
  A background reconciliation (the backfill script on a future cron) stays
  the ultimate safety net.
- **Zero-plugin compat.** No new plugin hooks, no changes to the plugin
  EventBus surface.
- **Async everywhere** for I/O. Neo4j paths unchanged (we only touch Qdrant).
- **Best-effort semantics consistent with Phase B.** Match
  `RawDocumentTarget.sync_downstream_stores` behaviour (MTRNIX-313): try,
  log on failure, never raise.

## Current state — what MTRNIX-313 gave us

Generalized freshness pipeline (`src/metatron/freshness/`):
- `targets.py::FreshnessTarget` Protocol has a `sync_downstream_stores`
  method with best-effort contract and no-raise guarantee.
- `stages/monitor.py` already calls
  `self._target.sync_downstream_stores(workspace_id, target_id,
  status=new_status, freshness_score=new_score)` after each lifecycle
  transition (post-STALE/SUPERSEDED/ARCHIVED).
- `stages/curator.py` does NOT call `sync_downstream_stores` — calls only
  `update_lifecycle` with `status=LifecycleStatus.ACTIVE`. Gap.
- `stages/reconciler.py` calls neither — it writes only `review_entries`,
  so no Qdrant sync is needed. Verified via full file read.
- `apply_decision.py` writes `status=LifecycleStatus.STALE` when
  `decision.action == "mark_stale"` and does NOT call
  `sync_downstream_stores`. Gap.

Memory adapter (`src/metatron/memory/freshness/target_memory.py`):
- `MemoryTarget.sync_downstream_stores` is a deliberate no-op today (Phase B
  comment: "Memory does not mirror status onto Qdrant chunk payloads in
  Phase B. Kept for interface symmetry; KB adapter overrides.").
- The adapter already knows how to resolve a per-workspace `MemoryQdrantStore`
  via `_resolve_qdrant(workspace_id)` — this is the only I/O we need.

KB adapter (`src/metatron/ingestion/freshness/target_raw_document.py`) —
serves as the reference pattern. `RawDocumentTarget.sync_downstream_stores`
payload-writes `{"status": ..., "freshness_score": ...}` via Qdrant, logs
failures at WARNING, never raises.

MCP-side (`src/metatron/memory/service.py::MemoryService.resolve_review`):
- After PR #89 (MTRNIX-319), the PG lifecycle update + review-entry delete +
  MachineEvent insert are one transaction via `pg_store.begin()` and the
  `conn` kwarg. Qdrant `update_payload` runs OUTSIDE the transaction, under
  `try/except Exception: logger.warning(...)`. This is the pattern we adopt
  for the worker.

Metrics (`src/metatron/freshness/metrics.py`):
- Contains `jobs_total`, `queue_depth_gauge`, `stage_duration`,
  `decision_confidence`, `worker_errors` — all guarded by a top-level
  `try/except ImportError` for `prometheus_client`. Each has a `_NoopMetric`
  fallback. Adding a new counter follows the exact same pattern.

`memory_records.status` write paths from the worker pipeline (after full
audit):

| Module | File | Writes `status`? | Currently calls Qdrant sync? |
|---|---|---|---|
| Linker | `freshness/stages/linker.py` | No — writes `evidence_count` only | N/A |
| Reconciler | `freshness/stages/reconciler.py` | No — writes `review_entries` only | N/A |
| FreshnessMonitor | `freshness/stages/monitor.py` | **Yes** — STALE/SUPERSEDED/ARCHIVED | **Yes, via `sync_downstream_stores` hook — but hook is a no-op for memory today** |
| Curator | `freshness/stages/curator.py` | **Yes** — CANDIDATE → ACTIVE | **No — missing hook call** |
| apply_decision | `freshness/apply_decision.py` | **Yes** — STALE when action=="mark_stale" | **No — missing hook call** |
| Reconciler alias graph | `freshness/stages/reconciler.py::alias_link_memory_items` | No (Neo4j only) | N/A |

Net: 3 real call sites → Monitor already has the hook (but hook is a
no-op); Curator and apply_decision need the hook added. The adapter's
`sync_downstream_stores` gets a real implementation.

## Decision: Option A vs Option B

The ticket's Recommended Placement section offers:

- **Option A** — new method on `MemoryTarget` (e.g. `apply_lifecycle(...)`)
  that does both PG + Qdrant writes atomically.
- **Option B** — post-hoc Qdrant sync in `apply_decision` plus stage-level
  direct calls where `apply_decision` is not used.

**Decision: Option A, but implemented as the already-existing
`FreshnessTarget.sync_downstream_stores` hook — not as a new
`apply_lifecycle` wrapper.** Reason:

- `sync_downstream_stores` already exists on the Protocol (MTRNIX-313).
  `FreshnessMonitor` already invokes it immediately after a lifecycle
  change. KB's `RawDocumentTarget` already implements it correctly.
  Introducing a parallel `apply_lifecycle` would duplicate the hook and
  desynchronize memory/KB semantics.
- Adding a new `apply_lifecycle(record_id, *, status, ...)` wrapper that
  wraps both `update_lifecycle` and `sync_downstream_stores` is tempting
  but adds a second way to do what a stage already does in two steps. The
  stages are canonical call sites and they are in the shared freshness
  submodule; centralising the Qdrant sync at the adapter's
  `sync_downstream_stores` keeps the Protocol small and the stage
  invocation identical between memory and KB.
- Option B (scatter `update_payload` in every stage) was rejected because
  it duplicates the try/except-log-swallow idiom across 3 files, adds a
  direct `MemoryQdrantStore` dependency to `apply_decision.py` (which
  today only knows about `FreshnessTarget`), and defeats the protocol
  abstraction.

So the design is "Option A, minimal surgery": make memory's
`sync_downstream_stores` non-no-op, and make sure every PG `status` mutation
site calls it. The hook contract (best-effort, never raises) is preserved
verbatim from the KB implementation.

### Method signature (unchanged from MTRNIX-313)

```python
async def sync_downstream_stores(
    self,
    workspace_id: str,
    target_id: str,
    *,
    status: LifecycleStatus,
    freshness_score: float,
) -> None:
    """Best-effort. NEVER raises. PG remains source of truth."""
```

The KB adapter writes both `status` and `freshness_score`. The memory
adapter writes only `status` because the MTRNIX-314 search filter only
pushes down on `status` (no `freshness_score` payload field exists on
memory Qdrant points yet — adding it is out of scope for this ticket).
`freshness_score` is accepted on the signature for symmetry but
deliberately dropped inside the memory adapter; documented with a
comment.

### Call-site checklist

| Site | Before | After |
|---|---|---|
| `FreshnessMonitor.run` (STALE/SUPERSEDED/ARCHIVED) | calls `sync_downstream_stores` (no-op for memory) | unchanged code; hook now writes Qdrant |
| `Curator.run` (CANDIDATE → ACTIVE) | calls `update_lifecycle` only | add `await self._target.sync_downstream_stores(..., status=ACTIVE, freshness_score=record.freshness_score or 0.5)` after `update_lifecycle` |
| `apply_decision.apply_decision` (mark_stale branch) | calls `target.update_lifecycle(status=STALE)` | add `await target.sync_downstream_stores(workspace_id, record.target_id, status=STALE, freshness_score=0.25)` after `update_lifecycle` |
| `apply_decision.apply_decision` (tag-only branch) | calls `target.update_lifecycle(append_tag=...)` | **no change** — status did not change, no Qdrant sync needed |
| Reconciler | writes `review_entries` only | **no change** |
| Linker | writes `evidence_count` only | **no change** |

### Why not touch `update_lifecycle` directly?

PG `update_lifecycle` is an L1 storage method. L1 does not talk to other
stores — that's the whole layering rule. Doing Qdrant sync inside
`update_lifecycle` would invert the layer hierarchy (L1 → calls L1 Qdrant
client, fine in principle, but couples what is currently a pure PG write
to a derived-store write with different failure semantics). Keeping the
sync at the adapter (L3-adjacent, inside `memory/freshness/`) matches
Phase B's layout and keeps `memory_postgres.py` pure PG.

## Open decisions — closed

### 1. Best-effort semantics

Every Qdrant write is wrapped in `try/except Exception` inside the
adapter:

```python
async def sync_downstream_stores(
    self, workspace_id, target_id, *, status, freshness_score,
) -> None:
    try:
        qdrant = await self._resolve_qdrant(workspace_id)
        await qdrant.update_payload(target_id, {"status": status.value})
    except Exception:
        logger.warning(
            "freshness.memory_target.qdrant_payload_sync_failed",
            workspace_id=workspace_id, target_id=target_id,
            status=status.value, exc_info=True,
        )
        metrics.qdrant_sync_failed.labels(
            target_kind="memory_record", stage="sync_downstream",
        ).inc()
```

Failures never propagate; PG transition stays committed; worker loop never
aborts. This matches `RawDocumentTarget.sync_downstream_stores` verbatim
(logger name + swallow pattern).

### 2. Ordering of writes

**Sequential, PG-first, best-effort Qdrant second. No shared transaction.**

Rationale:

- Atomicity across PG + Qdrant is not achievable (two different data
  stores, no XA / 2PC). A "shared transaction" via `pg_store.begin()` only
  makes the PG side atomic across multiple PG operations — which the
  worker's single `update_lifecycle` call already is.
- MTRNIX-319 (PR #89) made `resolve_review` atomic only across PG writes
  (update_lifecycle + delete_review_entry + save_machine_event — all on
  the same `conn`). The Qdrant `update_payload` in `resolve_review` runs
  OUTSIDE the transaction. We adopt the same pattern.
- PG is the source of truth. Lazy reconciliation (or a periodic backfill
  cron) is sufficient for derived-store catchup.
- Worker stage code already writes MachineEvent rows via
  `freshness_store.save_machine_event`; those are independent PG writes
  today (one per stage, one per job-processed). Not making them atomic
  with the lifecycle update is pre-existing behaviour; this ticket does
  not change it.

Worker-side atomicity across update_lifecycle + MachineEvent for
freshness stages is a separate concern and was explicitly discussed in
MTRNIX-319 commentary — out of scope here.

### 3. Metric surface

**Add `freshness.qdrant_sync_failed` counter.**

In `src/metatron/freshness/metrics.py`, extend the existing guarded block:

```python
qdrant_sync_failed: Any
try:
    from prometheus_client import Counter, ...
    ...
    qdrant_sync_failed = Counter(
        "freshness_qdrant_sync_failed_total",
        "Best-effort Qdrant payload sync failures by target kind / stage",
        ["target_kind", "stage"],
    )
    ...
except ImportError:  # pragma: no cover
    ...
    qdrant_sync_failed = _NoopMetric()
```

Add to `__all__`. Labels:

- `target_kind`: `"memory_record"` (and in future `"raw_document"` if KB
  wires the same counter — not in this ticket; MTRNIX-313 chose to log
  only).
- `stage`: `"sync_downstream"` for Monitor+Curator hook invocations,
  `"apply_decision"` for the apply_decision branch.

The metric is always present (stubbed when `prometheus_client` missing)
and does not add a runtime dep; callers can always `.labels(...).inc()`
without guarding on import. Matches existing `worker_errors` / `jobs_total`
style.

The `memory/freshness/metrics.py` re-export shim gets the new symbol added
to its import + `__all__` so `from metatron.memory.freshness.metrics
import qdrant_sync_failed` keeps working.

### 4. Legacy stage signatures

**No signature changes needed.** Every stage and `apply_decision` already
takes a `FreshnessTarget` instance (injected by the worker's pipeline
builder). The wiring (`worker.py` lines 307–357) instantiates
`MemoryTarget(pg_store=..., qdrant_store_factory=...)` and passes it in.
The adapter already has the `MemoryQdrantStore` factory handle required
for `sync_downstream_stores`. Zero wiring changes.

### 5. Test strategy for the Qdrant-failure path

**Unit tests.** Mock `MemoryQdrantStore.update_payload` to raise
`RuntimeError("qdrant down")`. Three targeted tests:

1. `test_memory_target_sync_downstream_swallows_qdrant_errors` —
   instantiate `MemoryTarget` with a mock Qdrant factory whose
   `update_payload` raises; call `sync_downstream_stores`; assert no
   exception, one WARNING log, counter incremented.
2. `test_curator_continues_on_qdrant_failure` — seed a CANDIDATE record
   with `evidence_count=1`, mock Qdrant to raise; call `Curator.run`;
   assert PG row transitioned to ACTIVE, `MachineEvent` saved, return
   value is `LifecycleStatus.ACTIVE`, counter incremented.
3. `test_apply_decision_mark_stale_syncs_qdrant_or_swallows` — mock
   `update_payload` success path: assert call args carry `status=stale`;
   failure path: assert no raise.

**Integration test.** One end-to-end run against live PG + Qdrant + Redis.
Approach: patch `MemoryQdrantStore.update_payload` at module boundary in
a test fixture to raise on alternating calls; assert PG transitions land,
MachineEvents land, and drift is eventually cleared by running the
backfill script. We do NOT stop the Qdrant container — too flaky in
CI and the behaviour we test (swallow + log + counter) is identical
whether the failure is a dropped socket or a Python exception.

**Live-data verification test** (the AC scenario). Seed a workspace,
enqueue a memory record, force-run the worker end-to-end (Monitor to
STALE via a past `valid_until`), then call `memory_search(status=["active"])`
via the MCP tool function and assert the record does NOT appear — without
running the backfill. This is the exact MTRNIX-319 §1 reproduction made
into a pass gate.

### 6. Backward compat with docs/MEMORY_MCP_FOLLOWUPS.md

**Remove item #4 entirely, and remove the #4 line in the trailing "Open
question" section of the doc.** Rationale: the follow-up doc is a triage
inbox. Once a ticket lands, the item's rationale lives in git history on
the spec commit. A "resolved in MTRNIX-322" stub would clutter the
remaining triage list; a reader encountering a "resolved" stub would
wonder whether action is still needed. Clean removal is the convention
other resolved ticket items follow (checked via git blame on prior
removals).

### 7. No `core/events.py` change

`FRESHNESS_*` event constants are unchanged. The worker does not emit a
new event for Qdrant sync — it writes the existing
`freshness_stage_completed` / `freshness_decision_applied` MachineEvent
rows, and the counter handles observability. A new event for
"qdrant_sync_failed" would be enterprise-facing noise. Out of scope.

## Data flow — before vs after

### Before (today, broken)

```
[Worker loop iteration]
  Linker.run(ws, id)                            # evidence_count only
  Reconciler.run(ws, id)                        # review_entries only
  Monitor.run(ws, id)                            # may write status=STALE
    → target.update_lifecycle(status=STALE)    [PG update OK]
    → target.sync_downstream_stores(...)       [NO-OP for memory]    <-- GAP
  Curator.run(ws, id)                           # may write status=ACTIVE
    → target.update_lifecycle(status=ACTIVE)   [PG update OK]
    [no sync_downstream_stores call]                                 <-- GAP
  apply_decision(...)                            # may write status=STALE
    → target.update_lifecycle(status=STALE)    [PG update OK]
    [no sync_downstream_stores call]                                 <-- GAP
```

Qdrant payload `status` stays `"active"` (original upsert value) →
`memory_search(status=["active"])` leaks the record.

### After

```
[Worker loop iteration]
  Linker.run(ws, id)                            # unchanged
  Reconciler.run(ws, id)                        # unchanged
  Monitor.run(ws, id)
    → target.update_lifecycle(status=STALE)
    → target.sync_downstream_stores(status=STALE, ...)
         ↳ MemoryTarget: try: qdrant.update_payload(id, {"status": "stale"})
                          except: WARN + counter.inc()                       # fixed
  Curator.run(ws, id)
    → target.update_lifecycle(status=ACTIVE)
    → target.sync_downstream_stores(status=ACTIVE, ...)                       # NEW
  apply_decision(...)  # mark_stale branch
    → target.update_lifecycle(status=STALE)
    → target.sync_downstream_stores(status=STALE, ...)                        # NEW
```

Derived store converges to PG within one worker iteration; failure
degrades gracefully and is observable via the counter.

## Adapter implementation

```python
# src/metatron/memory/freshness/target_memory.py

from metatron.freshness import metrics  # access qdrant_sync_failed counter

class MemoryTarget:
    ...
    async def sync_downstream_stores(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus,
        freshness_score: float,
    ) -> None:
        """Mirror the PG status into the memory Qdrant collection's payload.

        Best-effort: Qdrant is a derived store; failures are logged at
        WARNING, counted on the `freshness_qdrant_sync_failed` counter,
        and never propagate. PG remains the source of truth; the backfill
        script at ``scripts/backfill_memory_qdrant_status_payload.py`` is
        the long-tail safety net for persistent drift.

        ``freshness_score`` is accepted for interface symmetry with the
        KB adapter but not written — memory Qdrant points do not carry a
        ``freshness_score`` payload field in this ticket.
        """
        del freshness_score  # not written; see docstring
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
            except Exception:  # noqa: BLE001  — never let metrics bite
                pass
```

## Stage changes

### `freshness/stages/curator.py`

After the existing `await self._target.update_lifecycle(..., status=ACTIVE, ...)`
call and before the `save_machine_event`, insert:

```python
await self._target.sync_downstream_stores(
    workspace_id,
    target_id,
    status=LifecycleStatus.ACTIVE,
    freshness_score=record.freshness_score or 0.5,
)
```

(The `record.freshness_score or 0.5` fallback mirrors what the adapter
does for a freshly-seeded record; the value is only relevant to KB
targets today.)

### `freshness/apply_decision.py`

Inside the `if decision.confidence >= threshold:` block, specifically in
the `if decision.action == "mark_stale":` branch, after
`await target.update_lifecycle(..., status=LifecycleStatus.STALE, freshness_score=0.25, ...)`,
insert:

```python
await target.sync_downstream_stores(
    workspace_id,
    record.target_id,
    status=LifecycleStatus.STALE,
    freshness_score=0.25,
)
```

The tag-only branch (`elif joined_tag is not None:`) does NOT touch
`status`, so no sync is needed.

### Other stages

- `Linker` — no `status` writes; no change.
- `Reconciler` — no `status` writes; no change. (The "double-check" from
  the ticket description is resolved: the Reconciler writes
  `review_entries` + `machine_events` + a best-effort `:ALIAS` Neo4j
  edge. Zero PG `status` mutations.)
- `FreshnessMonitor` — already calls `sync_downstream_stores`; the hook
  becomes non-no-op. Code unchanged.

## Metric surface

One new counter in `src/metatron/freshness/metrics.py`:

```python
qdrant_sync_failed: Any

try:
    from prometheus_client import Counter, ...
    ...
    qdrant_sync_failed = Counter(
        "freshness_qdrant_sync_failed_total",
        "Best-effort Qdrant payload sync failures from the freshness pipeline",
        ["target_kind", "stage"],
    )
    ...
except ImportError:
    ...
    qdrant_sync_failed = _NoopMetric()

__all__ = [
    "decision_confidence",
    "jobs_total",
    "qdrant_sync_failed",   # NEW
    "queue_depth_gauge",
    "stage_duration",
    "worker_errors",
]
```

Shim update at `src/metatron/memory/freshness/metrics.py` — re-export the
new symbol for backward-compat imports.

## Search-side behaviour — unchanged

MTRNIX-314 filter semantics remain: missing `status` payload → treated as
ACTIVE (via `MatchAny` on excluded set, never `MatchValue` on included).
After this ticket, freshly-transitioned records carry the correct
`status` payload and are excluded by the `must_not` filter on the next
search. Backfill is only needed for pre-ticket records that the worker
has never re-touched since the gap existed.

No retrieval-pipeline changes. No `memory_search` / `memory_list` changes.
No Qdrant filter changes.

## Failure modes & edge cases

| Scenario | Behaviour | Observed via |
|---|---|---|
| Qdrant down during `sync_downstream_stores` | PG committed; Qdrant call raises; adapter catches, WARN + counter++; stage continues | log + Prometheus |
| Qdrant up but point missing (e.g. never upserted) | `set_payload` on a non-existent point raises — same swallow path; counter++ | log + Prometheus |
| Worker restarts mid-iteration, after PG commit, before Qdrant sync | Same final state as Qdrant-down: PG correct, Qdrant stale. Next worker iteration touches a different record; backfill or next transition clears it | existing |
| Two stages transition same record in same iteration (Curator → ACTIVE, Monitor → STALE) | Sequential PG writes + sequential Qdrant payload writes; last-write-wins. Stage lock prevents true concurrency | existing |
| Concurrent MCP resolve_review vs worker transition | Two independent PG `update_lifecycle` writes; last-write-wins on PG; respective Qdrant payloads converge to last PG state | existing Phase A behaviour |
| Record deleted between PG write and Qdrant sync | `set_payload` on missing point → swallow; backfill script idempotent | existing |
| `_resolve_qdrant` factory raises (e.g. misconfigured client) | Same swallow path; counter++ (labels attribute itself reentrant-safe) | log |

None of these require new handling beyond the existing swallow pattern.

## Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| New Qdrant traffic from Monitor's hook breaks existing Monitor latency budget | LOW | `update_payload` is a single-point-id write, O(ms). Monitor already syncs on every transition in KB path without incident. |
| Silent drift if Qdrant is chronically down | MEDIUM | `freshness_qdrant_sync_failed_total` counter + backfill script. Ops runbook: non-zero counter over 1h → run backfill. |
| Adapter import cycle: `memory.freshness.target_memory` imports `freshness.metrics` | LOW | `freshness.metrics` is L2 with no upward deps; safe import. |
| Double-write cost (PG + Qdrant now serialised inside stage) | LOW | Qdrant write is outside the PG transaction and best-effort — no extra PG lock time. Stage lock already serialises per-record. |
| Phase A regression — Monitor used to be a no-op for memory after `update_lifecycle`; now it does I/O | LOW | I/O was the design intent (hook exists for this reason). Tests assert the hook is called. |
| Counter labels grow unbounded | NONE | `target_kind` is bounded to `{memory_record, raw_document}`, `stage` to `{sync_downstream, apply_decision}`. Stable cardinality. |

## Coordination points

- **`core/interfaces.py`** — unchanged.
- **`core/events.py`** — unchanged. No new event constants.
- **`FreshnessTarget` Protocol** (`freshness/targets.py`) — unchanged;
  shape already supports this fix.
- **Enterprise repo** — no coordination needed. `FRESHNESS_*` event
  payloads unchanged. `MachineEvent` shape unchanged. PR body should
  still mention the new `freshness_qdrant_sync_failed_total` metric for
  enterprise dashboards that scrape Prometheus — courtesy only.
- **`docs/MEMORY_MCP_FOLLOWUPS.md`** — remove item #4 entirely
  (and the bullet for #4 in the trailing "Open question — should any of
  these be filed as tickets now?" section). Renumbering of items 1–3 is
  NOT needed — the sections use headings like "## 1." that remain
  stable; removing #4's block simply deletes those lines.

## Acceptance criteria (reviewer checklist, restated testably)

1. `make lint` — zero errors on changed files.
2. `make typecheck` — zero errors (mypy strict).
3. `make test` — all new unit tests pass; Phase A / Phase B / MTRNIX-314
   tests unchanged.
4. `make test-all` — integration suite passes against live
   PG + Qdrant + Redis.
5. `METATRON_FRESHNESS_ENABLED=true` worker run: seed an ACTIVE memory
   record with `valid_until < now`, run one worker iteration, call
   `MemoryQdrantStore.update_payload`-free search via `memory_search`
   with default filter — record MUST NOT appear. Assert WITHOUT running
   the backfill script.
6. Stop Qdrant client at the adapter (monkey-patch
   `MemoryQdrantStore.update_payload` to raise) for one worker iteration;
   PG row transitions, MachineEvent saved, counter
   `freshness_qdrant_sync_failed_total` incremented. Worker loop does NOT
   abort, does NOT raise.
7. Grep sanity:
   `grep -rn "update_payload" src/metatron/freshness/ src/metatron/memory/freshness/`
   → only inside `target_memory.py::sync_downstream_stores`. The call is
   centralised.
8. `grep -rn "workspace_id" src/metatron/memory/freshness/target_memory.py`
   hits every `update_payload` / `_resolve_qdrant` call.
9. No new imports from `agent/`, `channels/`, `api/routes/chat.py`,
   `api/routes/finops.py`.
10. `core/interfaces.py` unchanged. `core/events.py` unchanged.
11. `docs/MEMORY_MCP_FOLLOWUPS.md` item #4 removed.
12. PR body mentions the new Prometheus counter (courtesy for enterprise
    dashboards).
```

