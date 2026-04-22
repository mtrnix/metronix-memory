# Freshness Worker for KB `raw_documents` (Phase B) — Design

**Date:** 2026-04-22
**Jira:** MTRNIX-313 — Apply freshness worker to KB `raw_documents` (Phase B).
**Depends on:** MTRNIX-304 (Phase A — merged in PR #83).
**Sibling:** MTRNIX-314 (MCP lifecycle surface — review queue).
**Author:** Architect (agent-team)
**Status:** Draft — ready for implementation plan

## Goal

Extend the bounded, observable, pausable freshness pipeline (Linker → Reconciler →
FreshnessMonitor → Curator → DecisionEngine) built in Phase A onto the KB surface:
PostgreSQL `raw_documents` rows (and their Qdrant chunks). Same stages, same Redis
coordination primitives, same SLM-backed DecisionEngine, applied to a second
`target_kind="raw_document"`. No stage is forked; the five stage modules learn a
*target adapter* (Option A) so the KB case is "the same pipeline, different store."

The feature ships gated by two flags (`METATRON_FRESHNESS_ENABLED` master +
`METATRON_FRESHNESS_KB_ENABLED` KB-specific) so the rollout is: schema migration →
producer hook (flag off) → staging flip → eval → search-filter flip → prod.

## Non-goals

- SLM model tuning (Phase A already settled on `qwen2.5-4b-instruct-q4`; reuse).
- Control Center review queue UI (separate ticket).
- New MCP tool surface for KB status filtering (that's MTRNIX-314 scope extension).
- Ingesting legacy `raw_documents` as `CANDIDATE`. Legacy rows land as `ACTIVE` for
  backwards compatibility (see "Rollout").
- Replacing the existing `recency` scoring signal. Freshness is added as a new
  multiplicative signal, orthogonal to recency.
- Changing the Neo4j document graph schema (we add one optional property; no new
  node types or edges beyond what Phase A introduced for memory).

## Constraints

- **Layer boundaries.** All new code sits in `src/metatron/ingestion/freshness/`
  (L2 submodule of `ingestion/`) or touches existing L1 (`storage/`) and L0
  (`core/models.py`, `core/config.py`). No upward imports. No changes to
  `channels/`, `skills/`, `api/routes/chat.py`, `api/routes/finops.py` (legacy).
- **Zero-plugin compat.** Core must still work with no plugins installed.
- **Workspace isolation.** Every new column query, every Redis key, every Qdrant
  payload filter carries `workspace_id`.
- **Async everywhere** for I/O. Neo4j stays sync, called via `asyncio.to_thread`.
- **Eval non-regression.** `make eval-compare` at the pre-flight step. The
  search-filter flip lands behind its own flag so schema + worker can ship even if
  the filter flip is delayed pending eval investigation.
- **No new built-in chat UI, no new `/api/v1/chat/*` endpoint.**
- **Legacy:** no new functionality in `channels/`, `skills/`, `api/routes/finops.py`.

## Current state summary — what Phase A gave us

From PR #83 (MTRNIX-304), the following are reusable as-is for KB:

| Artefact | Location | Reuse for KB |
|---|---|---|
| `FreshnessJob` dataclass with `target_kind: str = "memory_record"` | `core/models.py` | **Yes.** Set `target_kind="raw_document"` for KB jobs. |
| `MemoryStatus` enum (CANDIDATE/ACTIVE/STALE/SUPERSEDED/ARCHIVED/CONFLICTED/REVIEW_NEEDED) | `core/models.py` | **Yes, renamed.** Promote to a shared `LifecycleStatus` StrEnum (alias `MemoryStatus = LifecycleStatus` for backward compat). |
| `FreshnessDecision` dataclass | `core/models.py` | **Yes.** Identical shape. |
| `ReviewEntry`, `MachineEvent` | `core/models.py` + `storage/memory_freshness_pg.py` | **Yes.** `target_kind` column already exists in `machine_events`; `review_entries` needs `target_kind` added + `record_id` generalized — see schema section. |
| Redis `CoordinationStore` (per-workspace LIST queues, Lua-scripted locks, checkpoints) | `memory/freshness/coordination.py` | **Yes, promoted.** Move to `src/metatron/freshness/coordination.py` (new shared submodule) so memory and KB both import from there. Memory's current import path kept via a re-export shim. |
| `CoordinationStore.list_active_workspaces()` scanning `freshness:queue:*` | same | **Yes** — same scan finds KB jobs because they use the same queue. |
| `FreshnessPostgresStore` (saves `review_entries`, `machine_events`) | `storage/memory_freshness_pg.py` | **Yes, renamed.** Rename the class to `FreshnessStore` (no "memory" prefix); move file to `storage/freshness_pg.py`. Add `target_kind` plumbing. |
| 14 `METATRON_FRESHNESS_*` env vars | `core/config.py` | **Reused.** Add 4 new KB-specific vars (see below). |
| 4 `FRESHNESS_*` event constants | `core/events.py` | **Reused verbatim.** Payload convention already carries `target_kind` via the job; KB jobs emit the same event names with `target_kind="raw_document"` in the payload. Enterprise subscribers see both kinds automatically. |
| `RuleBasedDecisionEngine` + `LLMBackedDecisionEngine` + `build_default_decision_engine()` | `memory/freshness/decision_engine.py` | **Yes, promoted.** Move the engine module to `src/metatron/freshness/decision_engine.py` (shared), keeping a re-export from the memory path. The prompt is still content-based — it does not care what kind of record it scores. |
| `metrics.py` Prometheus gauges/counters/histograms | `memory/freshness/metrics.py` | **Yes, promoted.** Move to `src/metatron/freshness/metrics.py`. Labels gain an optional `target_kind`. |
| Stages (`linker.py`, `reconciler.py`, `monitor.py`, `curator.py`) | `memory/freshness/` | **Refactored.** See "Generalizing the stages" — Option A. The stage *classes* stay memory-specific; what we add is a `FreshnessTarget` adapter protocol and a parallel `RawDocumentTarget` implementation, plus generalized stage drivers that take an adapter. Minimal surgery to Phase A. |
| `FreshnessWorker` | `memory/freshness/worker.py` | **Two workers, one shared loop.** See "Worker process". |
| Producer hook `enqueue_if_enabled` | `memory/freshness/producer.py` | **Kept memory-specific.** KB introduces a sibling `ingestion/freshness/producer.py` so the memory producer does not grow branches on `target_kind`. |

## Open decisions (12 questions, answered)

### 1. Queue topology — one queue or two?

**Decision: one shared per-workspace queue, distinguishing by `FreshnessJob.target_kind`.**

Rationale:
- `FreshnessJob.target_kind` exists already in Phase A and defaults to `"memory_record"`.
  The field is unused for any discriminating purpose today; Phase B gives it meaning.
- Workspace isolation is the important scope. Adding a second queue fans out the
  `list_active_workspaces()` scan pattern and makes two separate back-pressure
  regimes that need coordinated alerting. Throughput is not a concern at Phase B —
  KB is written to far less frequently than memory (sync cadence vs. per-prompt
  writes). A single queue simplifies the dashboards.
- The worker dispatches per job on `job.target_kind` — cheap switch at the top of
  `_process_job`. No cross-contamination: if `target_kind` is unknown, the worker
  logs and skips (forward-compat).
- Back-pressure argument for separation is real but small: a burst of KB sync
  traffic could push memory jobs down the queue. Mitigation: the worker runs
  `dequeue_batch` which is bounded; job order within a workspace does not affect
  correctness (jobs are idempotent and re-runnable). If production shows a
  starvation pattern, we can lift to two queues later — the `target_kind` field
  already carries the information needed to shard.

### 2. Worker process — one or two?

**Decision: one worker process, two "pipelines," one shared loop.**

The worker (`python -m metatron.memory.freshness`) stays as the entry point for
compatibility. It builds both a `MemoryFreshnessPipeline` and a
`RawDocumentFreshnessPipeline`, each holding their own stage-adapter stack. The
`FreshnessWorker._process_job` switches on `job.target_kind` and routes to the
right pipeline.

Docker compose stays single-service `--profile freshness`. No separate
`freshness-kb-worker`. Rationale: same operational footprint, one set of logs,
one metrics scrape target, one backoff. If memory load dominates and starves KB
(not expected), we can split later. The worker builds both pipelines unconditionally
when `METATRON_FRESHNESS_ENABLED=true`; the KB pipeline short-circuits inside its
own producer when `METATRON_FRESHNESS_KB_ENABLED=false`, so flipping KB off does
not require restarting the worker.

### 3. Generalizing the stages — adapters (A) or duplication (B)?

**Decision: Option A — `FreshnessTarget` adapter protocol with two implementations.**

Rationale:
- The Phase A plan explicitly left this door open ("If Phase B shows KB needs the
  same protocol, we lift DecisionEngine into `core/interfaces.py` then.") KB is
  now concrete; the shape is concrete.
- Duplication doubles the surface, and every bug fix to a memory stage would have
  to be ported. The stages are small (60–210 lines each); the *variability* is
  small (which store to `get` from, which `update_lifecycle` to call, which
  Qdrant search method, which Neo4j edge helper). A Protocol captures exactly
  that.
- The Protocol lives in `src/metatron/freshness/targets.py` (a new shared
  submodule under `ingestion/`-adjacent namespace). Promoting it into
  `core/interfaces.py` is not required yet — the Protocol is used only inside
  the freshness subtree. Premature promotion of a Protocol to `core/` locks
  enterprise to a shape we might still tune during KB development. **Deferred to
  after MTRNIX-313 lands and stabilizes.**

Adapter surface:

```python
class FreshnessTarget(Protocol):
    kind: str  # "memory_record" | "raw_document"

    async def get(self, workspace_id: str, target_id: str) -> FreshnessTargetRecord | None: ...
    async def update_lifecycle(
        self, workspace_id: str, target_id: str, *,
        status: LifecycleStatus | None = None,
        freshness_score: float | None = None,
        superseded_by: str | None = None,
        evidence_count: int | None = None,
        verification_state: str | None = None,
        valid_until: datetime | None = None,
        append_tag: str | None = None,
    ) -> None: ...

    async def similarity_search(
        self, workspace_id: str, content: str, *, top_k: int
    ) -> list[SimilarityHit]: ...

    async def link_edges_batch(
        self, workspace_id: str, source_id: str, edges: list[tuple[str, float]]
    ) -> None: ...  # best-effort, NEVER raises

    async def alias_edge(
        self, workspace_id: str, source_id: str, target_id: str
    ) -> None: ...  # best-effort, NEVER raises
```

`FreshnessTargetRecord` is a thin DTO that exposes what the stages need
(`content`, `tags`, `status`, `valid_until`, `superseded_by`, `updated_at`,
`freshness_score`, `evidence_count`). It is *not* a new core dataclass — it lives
in `freshness/targets.py` as a dataclass local to the module. Memory and KB
adapters return instances constructed from `MemoryRecord` / `RawDocument`
respectively.

The five stage classes are rewritten to take a `FreshnessTarget` instead of the
concrete `MemoryPostgresStore` + `QdrantStoreFactory` pair. Phase A tests keep
passing because the memory adapter is a thin wrapper around the existing stores.

### 4. Schema on `raw_documents`

**Decision: 7 lifecycle columns, symmetric to `memory_records`, plus one KB-specific column for the provenance chain.**

New columns (Alembic migration 018):

| Column | Type | Default | Purpose |
|---|---|---|---|
| `status` | TEXT | `'active'` | Lifecycle status (lowercase strings matching `LifecycleStatus` enum values). Check constraint: `IN ('candidate','active','stale','superseded','archived','conflicted','review_needed')`. |
| `freshness_score` | FLOAT | `0.5` | FreshnessMonitor-computed, `[0.0..1.0]`. |
| `superseded_by` | TEXT | `NULL` | `raw_documents.id` of the newer doc that replaces this one, when known. |
| `valid_until` | TIMESTAMPTZ | `NULL` | Explicit expiry (e.g. "deprecated on 2026-06-01"). Past → ARCHIVED. |
| `evidence_count` | INTEGER | `0` | Number of related documents found by Linker (used by Curator). |
| `verification_state` | TEXT | `NULL` | Free-form audit label (`connector_materialized`, `pending_review`, `llm_verified`, ...). |
| `last_freshness_run_at` | TIMESTAMPTZ | `NULL` | Last time the FreshnessMonitor ran. Used by the scheduled scan (not this ticket — a follow-up) to cap first-run bulk churn. |

Explicitly **not added** on the `raw_documents` table:
- `valid_from` — not used; `raw_documents.fetched_at` covers the provenance first-seen stamp.

Index additions:
- `ix_raw_docs_ws_status(workspace_id, status)` — supports the retrieval-side
  "WHERE status != 'archived'" pushdown if we ever run PG-joined filtering.
- `ix_raw_docs_ws_valid_until(workspace_id, valid_until) WHERE valid_until IS NOT NULL` — supports the FreshnessMonitor scheduled scan.

Enum is modelled as TEXT + CHECK constraint (not a Postgres ENUM type). Phase A
did the same for `memory_records.status`. Consistency with Phase A + easier
additions in future migrations without DDL surgery. Python-side still uses the
`LifecycleStatus` StrEnum, sharing the values across both tables.

Backwards compat: all existing `raw_documents` rows land with `status='active'`,
`freshness_score=0.5`, everything else NULL/0. Current search queries are
untouched because they don't SELECT the new columns. The retrieval filter flip
(search-filter phase) is guarded by its own flag.

### 5. Ingestion hook — where does a new KB row land as `CANDIDATE`?

**Decision: per-document enqueue from `postgres.upsert_raw_documents`, via the changed-source-ids return. Status on *legacy* rows stays `ACTIVE` forever; status on *new* rows after the cutover stays `ACTIVE` too. `CANDIDATE` is reserved for a follow-up once the Curator has a KB evidence rule we trust (see #6).**

Rationale:
- Phase A memory lands new records directly as `CANDIDATE` because the Curator's
  evidence rule (`evidence_count >= 1`) is meaningful for ephemeral chat writes.
- For KB, making new connector-synced docs go to `CANDIDATE` would either stall
  search for new docs (ARCHIVED/CANDIDATE would be filtered out once we flip the
  filter) or force us to set an evidence rule that almost always promotes (so
  `CANDIDATE` becomes meaningless). Both outcomes are worse than "status stays
  `ACTIVE`, freshness downgrades kick in over time."
- So Phase B defines the *status transitions* (ACTIVE → STALE, ACTIVE → SUPERSEDED,
  ACTIVE → ARCHIVED) and leaves the ACTIVE → CANDIDATE path out. A follow-up
  (not this ticket) can flip new docs to land as `CANDIDATE` once we pick a
  KB-appropriate evidence rule.

What ships in this ticket:
- `postgres.upsert_raw_documents` returns `changed_source_ids` (already does).
- A new helper `ingestion/freshness/producer.py::enqueue_raw_document_if_enabled(workspace_id, raw_document_id, event_type)` is called by the ingestion pipeline after the upsert returns, once per changed id.
- The enqueue is gated on `METATRON_FRESHNESS_ENABLED AND METATRON_FRESHNESS_KB_ENABLED`. Off → no-op, byte-identical behaviour.
- Event type is `"knowledge_changed"` for new rows, `"content_changed"` for updated ones (distinguishable at call site via `upsert_raw_documents` return: new vs. updated; today it returns both in the same list, so the producer takes the event_type as a parameter and the caller knows which is which).
- The producer is called from:
  - `api/routes/connections.py::_run_connection_sync` (connector sync entry point) — **after** `upsert_raw_documents` succeeds.
  - `ingestion/pipeline.py::ingest_documents` — **after** the raw_document has been persisted, if this code path ever bypasses `upsert_raw_documents`. (In current code it doesn't; `upsert_raw_documents` is always called from the connections route before the pipeline. But chat.py upload path calls `ingest_documents` directly with in-memory `Document` objects; that path does *not* go through `upsert_raw_documents` and therefore does not enqueue a job — acceptable for Phase B because those are single-shot user uploads outside the connector sync flow, not the primary target.)
  - Hook point for file upload path is a Phase B/C follow-up (tracked as a todo in the producer docstring).

Failure mode: producer swallows Redis errors (same policy as memory producer).
A dropped enqueue does not corrupt state — the scheduled-scan safety net will
catch stale docs eventually.

### 6. CANDIDATE → ACTIVE auto-promotion via Curator

**Decision: Curator is a no-op for KB in Phase B.** Skip promotion entirely when `target_kind="raw_document"`.

Rationale:
- Legacy rows land as `ACTIVE` (decision #5 above). New rows land as `ACTIVE`.
  There's nothing to promote.
- The stage still gets called for interface consistency, but the `Curator.run`
  implementation returns `None` for KB adapter (via a `supports_candidate_promotion`
  flag on the adapter). Memory adapter: `True`; KB adapter: `False`. The flag
  lets the Curator skip all work without an allocations/lock round-trip.
- When a follow-up ticket lands KB's `CANDIDATE` path (e.g. "land as CANDIDATE,
  promote only if doc has ≥N chunks indexed + chunks have non-empty content
  fingerprints + title is non-empty + first chunk is not near-duplicate to any
  existing chunk"), this flag flips and the Curator gets KB semantics.

### 7. Search-pipeline integration

**Decision: layered — Qdrant payload filter (ARCHIVED excluded), retrieval-level filter (SUPERSEDED excluded), scoring-level down-weight (STALE gets a multiplicative penalty). All three behind a single feature flag `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED`, separate from `METATRON_FRESHNESS_KB_ENABLED`, so the schema/worker/ingestion-hook can ship independent of the retrieval flip.**

Layers:

1. **Qdrant payload filter** (hardest exclusion, cheapest to evaluate server-side).
   Chunks in the KB Qdrant collection gain two payload fields: `status` and
   `freshness_score` — kept in sync with the parent `raw_documents` row.
   - **Write path:** `raw_document.status` changes → worker calls a new
     `AsyncQdrantVectorStore.update_payload_by_doc_label(status=, freshness_score=)`
     method that sets the payload on all chunks with the matching `doc_label`.
     Best-effort; failures logged, not raised.
   - **Read path:** when the flag is on, each recall channel adds a payload
     filter equivalent to `status != 'archived'` to its Qdrant query, combined
     with the existing `access_filter` via `must`. Channels already take an
     `access_filter` kwarg (see `retrieval/channels.py:recall_dense_async`);
     the new filter is built in `retrieval/search.py` alongside `access_filter`
     and passed through the same `RecallContext` field.
2. **Retrieval-level filter** (for anything that doesn't go through Qdrant —
   `recall_metadata` uses PG-level search_by_status / search_by_assignee; those
   methods grow a `exclude_archived=True` default-True parameter. `recall_graph`
   queries Neo4j for doc_labels — it stays status-agnostic because Neo4j does
   not carry `status` in Phase B; post-filter via a PG lookup against
   `raw_documents.status` for the returned doc_labels. Tiny batched query.)
3. **Scoring-level down-weight** — a new `freshness` signal fed into
   `compute_signal_score`. Weight: `METATRON_FRESHNESS_WEIGHT`, default `0.00`
   (OFF until we tune). Value range `[0.0..1.0]`, derived from
   `raw_documents.freshness_score` for the hit's `doc_label`. Because the weight
   default is 0.0, the scoring formula is numerically identical to today until
   someone flips the weight. The `signal_score` denominator adjusts for the new
   weight via the existing `weight_sum` normalization (line 93 of `scoring.py`).

Feature flag:
- `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED` (default `false`) controls
  layers 1 and 2 (filtering). When `false`, channels behave exactly as they do
  today.
- `METATRON_FRESHNESS_WEIGHT` defaults to `0.0`. When `>0`, layer 3 activates.
  (No separate flag — the weight itself is the switch.)

Rollback: flip either flag back to false. Schema columns and Qdrant payload
changes do not hurt anyone at rest.

### 8. Qdrant side

**Decision: add `status` and `freshness_score` to KB chunk payloads, sync from worker.**

Chunks in `metatron_{ws}` collection already carry metadata (title, type, etc.).
Adding two string/float fields is a payload-only change, no vector index change.
No collection migration needed — Qdrant accepts new payload fields without
recreating the collection.

Backfill strategy for existing chunks:
- Skip bulk backfill. New `upsert_chunks` calls write the payload (ingestion side
  — small code change); existing chunks get the payload lazily when the
  FreshnessMonitor first touches their parent doc.
- For the first production rollout, optional one-shot script
  `scripts/backfill_raw_doc_freshness_payload.py` writes `status='active',
  freshness_score=0.5` onto all existing chunks for a workspace. Runs
  idempotent by matching chunks whose payload lacks `status`. Shipping the
  script is Phase B; *running* it is a deployment decision, not a code change.

### 9. Neo4j side

**Decision: no new node types or edges. Add one optional `status` property to `:Document` nodes (write path only).**

The retrieval graph channel (`recall_graph`) doesn't currently know about status
and doesn't need to. Graph-traversal results are post-filtered by the
retrieval-level filter (layer 2 above). Adding a property on `:Document` lets
future work push the filter into the Cypher query, but we don't use it in Phase B.

No index on the property. No backfill.

### 10. Backward compatibility & rollout

**Decision: two-flag rollout, five ordered phases.**

Flags:
- `METATRON_FRESHNESS_ENABLED` (master, default `false`) — gates both memory and KB producers.
- `METATRON_FRESHNESS_KB_ENABLED` (default `false`) — gates the KB producer specifically, so KB can be turned off while memory stays on.
- `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED` (default `false`) — gates the retrieval filter.

Rollout order:

1. **Schema** — migration 018 lands, adds columns, existing data is `ACTIVE/0.5/NULL`.
   No runtime behaviour change. Shippable alone.
2. **Code (flags off)** — Phase B producer, stage adapters, worker routing all
   ship; flags all default off. Shippable alone. Existing memory-only
   freshness flows unchanged.
3. **Staging flip** — ops enables `METATRON_FRESHNESS_ENABLED=true` and
   `METATRON_FRESHNESS_KB_ENABLED=true` in staging. Worker starts producing
   KB status transitions in the background. Search unaffected (filter flag off).
4. **Eval gate** — run `make eval-compare` in staging with the filter flag flipped
   on. Regression vs. baseline must be within **±0.5 pp nDCG@10** (agreed
   2026-04-22). If regressed, investigate; do not flip in prod.
5. **Production flip** — enable all three flags in prod. Monitor.

Bulk first-run risk (STALE avalanche) — real for KB more than for memory. Two
mitigations baked into the plan:
- **Age-gate on first FreshnessMonitor run per doc.** The Monitor only demotes to
  STALE when `updated_at <= now - stale_after_days AND last_freshness_run_at IS
  NULL` → set `last_freshness_run_at=now` and transition. On subsequent runs the
  `updated_at` check stays the same. This is a one-line change in `monitor.py`
  to support the adapter's `last_freshness_run_at` field.
- **Rate-limit via the existing bounded loop.** `MAX_JOBS_PER_ITERATION=20`,
  `POLL_SECONDS=2.0` already throttles to ~600 jobs/min per worker. Not a hard
  mitigation but it spreads the churn.

Not attempted: a "first-run freshness deadline" that delays all downgrades for N
days post-enable. The agreed approach is "let STALE land incrementally, but do
not filter STALE out of search — just down-weight." So even a big STALE wave
causes no recall loss, just recall reordering.

### 11. Interfaces coordination

**Decision: no changes to `core/interfaces.py` in Phase B.** The `FreshnessTarget`
Protocol lives at `src/metatron/freshness/targets.py` — shared between memory
and KB, but not elevated to `core/interfaces.py`. Rationale identical to Phase A:
the Protocol shape is now stable across two implementations, but lifting it to
`core/interfaces.py` forces enterprise repo coordination for every future tweak.
Lift in a follow-up once the shape has been stable for a release cycle.

### 12. Enterprise coordination

**Decision: no new event constants.** The four `FRESHNESS_*` constants added in
Phase A cover KB too, because the event payload already carries
`target_kind` (derived from the job). The enterprise subscribers subscribed
to `FRESHNESS_DECISION_APPLIED` and `FRESHNESS_REVIEW_CREATED` will see both
`target_kind="memory_record"` and `target_kind="raw_document"` events after
Phase B lands. This is additive, non-breaking.

**ENTERPRISE COORDINATION REQUIRED:** only as a courtesy heads-up in the PR
description — subscribers may wish to filter on `target_kind` if they only
want memory events (today's implicit behaviour). Plan's documenter step adds
a bullet to the PR template.

No changes to `core/interfaces.py`. No changes to existing event names.

## Target schema on `raw_documents`

Full column list after migration 018:

```
id                     TEXT PK
workspace_id           TEXT
connector_type         TEXT
connection_id          TEXT
source_id              TEXT
title                  TEXT
content                TEXT
url                    TEXT
author                 TEXT
content_hash           TEXT
metadata               JSONB
source_role            TEXT
qdrant_synced          BOOLEAN
graph_synced           BOOLEAN
qdrant_synced_at       TIMESTAMPTZ
graph_synced_at        TIMESTAMPTZ
fetched_at             TIMESTAMPTZ
created_at             TIMESTAMPTZ
updated_at             TIMESTAMPTZ
source_created_at      TIMESTAMPTZ
source_updated_at      TIMESTAMPTZ
-- NEW (migration 018):
status                 TEXT NOT NULL DEFAULT 'active'
freshness_score        FLOAT NOT NULL DEFAULT 0.5
superseded_by          TEXT NULL
valid_until            TIMESTAMPTZ NULL
evidence_count         INTEGER NOT NULL DEFAULT 0
verification_state     TEXT NULL
last_freshness_run_at  TIMESTAMPTZ NULL
```

Check constraint: `status IN ('candidate','active','stale','superseded','archived','conflicted','review_needed')`.

Indexes:
- `ix_raw_docs_ws_status(workspace_id, status)`
- `ix_raw_docs_ws_valid_until(workspace_id, valid_until) WHERE valid_until IS NOT NULL`

Downgrade drops the columns and indexes.

### Supporting tables touched

- `review_entries` — add `target_kind TEXT NOT NULL DEFAULT 'memory_record'` and rename `record_id → target_id` (via ALTER; keep `record_id` as a rename, not a duplicate). Update `FreshnessStore.save_review_entry` to write `target_kind` from the argument. Backward-compat: `record_id` field on the dataclass kept as an alias (Python side); DB column renamed. Migration 018 handles the DB rename.
- `machine_events` — no DDL change needed. Phase A migration already included `target_kind` and `target_id`.

## Queue & worker topology

- **Queue keys** (reused verbatim from Phase A): `freshness:queue:{workspace_id}`.
  Both memory and KB jobs land here. Discriminated by `target_kind`.
- **Locks:** `freshness:{stage}:{target_kind}:{target_id}` — add `target_kind`
  to the key to avoid accidental collisions between memory-record-id and
  raw-document-id UUIDs. Backward-compat: memory stages currently use
  `freshness:{stage}:{target_id}`; the new key builder does
  `freshness:{stage}:{target_kind_or_legacy}:{target_id}` where
  `target_kind_or_legacy` is `""` for memory (empty prefix = same key as
  Phase A). So memory locks do not change shape, and KB locks cannot collide.
- **Checkpoints:** same as locks, with stage prefix instead of stage:target_kind.
- **Worker:** one process, two pipeline stacks. `_process_job` dispatches on
  `target_kind`. Unknown `target_kind` → log + skip (forward-compat for an
  eventual "assertion" or "file" kind).

## Producer hook points

- `src/metatron/ingestion/freshness/producer.py::enqueue_raw_document_if_enabled(workspace_id, raw_document_id, event_type)`
  - No-op when `freshness_enabled=False OR freshness_kb_enabled=False`.
  - Fail-soft: Redis errors logged, not raised.
  - Shared `CoordinationStore` singleton (lifted to `src/metatron/freshness/producer_common.py` and reused by memory producer — the Phase A `_build_default_coordination` helper is already ready for this).
- **Call sites in this ticket:**
  - `api/routes/connections.py::_run_connection_sync` — loops over
    `upsert_result["changed_source_ids"]`, looks up each `raw_documents.id` by
    `(workspace_id, connector_type, source_id)` using `get_raw_document`, and
    calls the producer once per changed id. This lookup exists; we just call
    it once more for enqueueing. Batch-size hint: 50. If the sync churns 10k
    docs, this is 10k Redis LPUSH calls behind a feature flag — acceptable,
    but the plan notes batching as a future optimisation.
  - Any direct caller of `PostgresStore.upsert_raw_documents` — only the one
    above at present.
- **Explicitly NOT hooked in this ticket:**
  - Chat `POST /api/v1/upload` path (file ingestion). Marked as TODO in the
    producer docstring. Phase C concern.

## Stage behaviour for KB target

Every stage takes a `FreshnessTarget` adapter. The `RawDocumentTarget`
implementation is in `src/metatron/ingestion/freshness/target_raw_document.py`.

### Linker (KB)
- Same algorithm: top-K similarity search, filter by threshold, count hits.
- `similarity_search`: uses the workspace's `metatron_{ws}` Qdrant collection
  via `get_async_hybrid_store(ws).hybrid_search`. Top-K = 20 (same as memory).
  Hits filtered by `doc_label != self`, `score >= threshold`. Since Qdrant
  chunks belong to `raw_documents` at different granularities, the hit set is
  deduplicated by `doc_label` (the chunk's `doc_label` payload = parent
  raw_document id) before counting.
- `update_lifecycle(evidence_count=N)` writes to `raw_documents`.
- `link_edges_batch`: creates `(:Document)-[:RELATED_TO {score}]->(:Document)`
  edges in Neo4j (best-effort). This is a new edge type; adding it is
  additive in Neo4j. The cypher helper lives in `storage/raw_document_graph.py`
  (new file) — batched UNWIND pattern, same shape as Phase A's
  `link_memory_items_batch`.

### Reconciler (KB)
- Threshold `>=0.85` same as memory.
- Finds near-duplicate `raw_documents` by same Qdrant query, dedup by `doc_label`.
- Writes `ReviewEntry(target_kind="raw_document", target_id=raw_document_id,
  related_record_id=related_raw_doc_id, reason="possible_duplicate")`.
- `alias_edge`: `(:Document)-[:ALIAS]->(:Document)` best-effort.
- Idempotent via `FreshnessStore.find_review_entry` (unchanged from Phase A).

### FreshnessMonitor (KB)
- Exact same rules, on `raw_documents.valid_until / superseded_by /
  source_updated_at` (KB uses `source_updated_at` rather than `updated_at`
  when available, falling back to `updated_at`) vs. `stale_after_days`.
- Sets `last_freshness_run_at = now` on first touch (age-gate).
- Writes status + freshness_score via `update_lifecycle`.

### Curator (KB)
- **No-op** in Phase B. See decision #6. `RawDocumentTarget` returns
  `supports_candidate_promotion=False` and the Curator stage short-circuits
  without acquiring a lock.

### DecisionEngine (shared)
- Unchanged. Prompt takes the record's `content`; doesn't care about target kind.
  `apply_decision` routes lifecycle updates through the target adapter, so the
  same function handles both memory and KB.

### Qdrant payload sync hook
- After FreshnessMonitor changes `status` or `freshness_score` on a
  `raw_document`, the worker calls
  `AsyncQdrantVectorStore.update_payload_by_doc_label(workspace_id,
  doc_label=raw_document_id, payload={status: ..., freshness_score: ...})`.
- Best-effort, wrapped in try/except — worker does not fail if Qdrant write
  fails; event log captures the attempt.

## Search-pipeline integration plan

Concrete call-site changes (all gated by
`METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED` when filtering, by
`METATRON_FRESHNESS_WEIGHT > 0` when scoring):

### Filter pushdown

- **`retrieval/search.py`**: build a `freshness_filter: Filter | None` alongside
  `access_filter` in `_setup_retrieval_context`. When the flag is on:
  ```python
  from qdrant_client.http.models import FieldCondition, Filter, MatchValue, MatchExcept
  freshness_filter = Filter(must=[FieldCondition(key="status", match=MatchExcept(**={"except": ["archived"]}))])
  ```
  (Qdrant `MatchExcept` — use `MatchValue(value="active")` OR'd with `MatchValue(value="candidate")` OR'd with `MatchValue(value="stale")` etc. if `MatchExcept` is not in our client version; plan includes a compatibility check step.)
- **`retrieval/channels.py`**: thread `freshness_filter` through `RecallContext`
  and combine with `access_filter` via `Filter(must=[...all_filters_must])`
  inside each recall channel's dispatch. Graceful: if `freshness_filter` is
  `None`, code path is byte-identical to today.
- **`recall_metadata`**: the PG-backed `search_by_status` / `search_by_assignee`
  methods add an optional `exclude_archived: bool = True` parameter that adds
  `AND status != 'archived'` to the WHERE clause. When KB filter flag is off,
  caller passes `exclude_archived=False` to preserve current behaviour.
- **`recall_graph`**: Neo4j results are post-filtered. After the channel
  collects doc_labels from graph traversal, a single batched
  `SELECT id, status FROM raw_documents WHERE workspace_id=$1 AND id = ANY($2)`
  call drops rows with `status='archived'` (or `'superseded'`). Implemented in
  `recall_graph_async`.

### Scoring down-weight

- **`retrieval/scoring.py::compute_signal_score`**: new parameter
  `freshness: float = 1.0` (neutral default) and
  `freshness_weight: float = 0.0` (neutral default). When `freshness_weight > 0`
  it joins the linear blend and the weight-sum normalization. When 0, the
  formula is numerically identical to today (the new term contributes 0 to
  numerator and 0 to denominator).
- **`retrieval/search.py`**: after building the merged-candidate list, enrich
  each merged result with its parent `raw_documents.freshness_score` via a
  single batched PG lookup. Batching key is the distinct set of `doc_label`s
  across the top-35 rerank pool — small. Pass `freshness=doc.freshness_score`
  into `compute_signal_score`. If the lookup fails, default to `1.0`
  (graceful degradation — never fail search).

### Eval regression risk

- **Risk:** flipping the filter flag removes ARCHIVED docs from all channels.
  If a real query's gold answer happens to be in an ARCHIVED doc (it
  shouldn't be, by definition, but legacy rows all land as `ACTIVE` so
  this only bites once curators start archiving docs), recall drops.
- **Mitigation:** eval gate. `make eval-compare` must show no regression
  before flipping in prod.
- **Risk:** STALE-heavy dataset + `freshness_weight` turned up too high could
  reorder top-10 results. Default weight = `0.0` — stays numerically
  identical to today. Flipping weight up is a tuning decision with its own
  grid-search + eval pass.

## Rollout plan

Mirrors "Open decision #10". See that section for ordered phases.

## Test strategy

### Unit tests
- `tests/unit/ingestion/freshness/test_producer_raw_document.py` — flag off → no-op, flag on → LPUSH with correct payload, Redis error → fail-soft.
- `tests/unit/ingestion/freshness/test_target_raw_document.py` — adapter methods: get, update_lifecycle (all 7 lifecycle fields), similarity_search dedup by doc_label, link_edges_batch no-raise, alias_edge no-raise.
- `tests/unit/freshness/test_stages_with_raw_document_target.py` — run each stage (Linker/Reconciler/Monitor/Curator no-op/DecisionEngine/apply_decision) with a mock `RawDocumentTarget`, assert lifecycle transitions + MachineEvent rows + idempotency on rerun.
- `tests/unit/storage/test_raw_documents_lifecycle.py` — new `PostgresStore.update_raw_document_lifecycle` method, row mapper reads the 7 new columns, indexes exist.
- `tests/unit/storage/test_raw_document_qdrant_payload.py` — `AsyncQdrantVectorStore.update_payload_by_doc_label` happy path + partial-batch failures.
- `tests/unit/retrieval/test_freshness_filter_pushdown.py` — flag off → no Filter added, flag on → Filter combines correctly with `access_filter`, PG post-filter on graph results.
- `tests/unit/retrieval/test_compute_signal_score_with_freshness.py` — weight=0.0 → numerically identical, weight>0 → denominator adjusts, recency and freshness are independent.
- `tests/unit/memory/freshness/test_stage_adapter_compat.py` — memory target adapter still passes Phase A stage tests (regression guard).

### Integration tests
- `tests/integration/ingestion/freshness/test_end_to_end_raw_document.py` — ingest a doc via `upsert_raw_documents` with flag on → worker run_once → PG status transitions + MachineEvent + Qdrant payload + Neo4j edge + review entry (when duplicate).
- `tests/integration/retrieval/test_search_with_freshness_filter.py` — index two docs (one ARCHIVED, one ACTIVE) → search returns only ACTIVE when filter flag on; returns both when off.

### Eval
- `make eval-compare` at the pre-flight step, with filter flag on. Must show no regression vs. baseline.

## Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Eval regression on filter flip | HIGH | Separate flag; eval gate before prod flip. Schema + worker ship unflipped. |
| STALE avalanche on first run | MEDIUM | Age-gate via `last_freshness_run_at`. Filter does not exclude STALE (only ARCHIVED/SUPERSEDED). STALE only affects scoring weight, default 0.0. |
| Qdrant payload drift (status on chunks out of sync with PG) | MEDIUM | Best-effort writes + structured logging. Scheduled consistency check job (not this ticket) later. Search filter only gates ARCHIVED; drift would at worst exclude a doc briefly or include one briefly. |
| Worker single-process starvation (memory jobs starve KB) | LOW | Shared queue, per-workspace bounded batches. If observed, split queues later (topology supports it — `target_kind` carries the info). |
| Producer stampede on 10k-doc sync | LOW | Fail-soft + batch-size-friendly Redis LPUSH. Enterprise can add batch-enqueue later if metrics show hot loop. |
| `FreshnessTarget` Protocol shape wrong for Phase C (e.g. "Assertion" target kind) | LOW | Protocol lives in `freshness/targets.py` (not `core/interfaces.py`). Deferred promotion until shape stabilizes across three implementations. |
| Review-entry `record_id → target_id` rename breaks Control Center plugin | LOW-MEDIUM | Python dataclass keeps backward-compat field alias; DB column is renamed atomically via Alembic. Plugin consumers read from the dataclass. PR body flags this explicitly for enterprise. |

## Coordination points

- **No changes to `core/interfaces.py`.**
- **No changes to `core/events.py`.** Event payloads gain richer `target_kind` data (additive).
- **`review_entries` table:** column rename `record_id → target_id` — Alembic migration 018 handles it. Python dataclass `ReviewEntry` keeps both field names during a deprecation window (field default shadowing). **ENTERPRISE COORDINATION REQUIRED** only if the Control Center plugin queries `review_entries` directly by column name. If it uses the `FreshnessStore.list_review_entries` Python API, no code change needed.
- **`FRESHNESS_*` events** now carry both `target_kind` values (`memory_record` + `raw_document`). **ENTERPRISE COURTESY HEADS-UP** in PR description — subscribers may want to filter on `target_kind`.
- **Shared freshness submodule:** Phase A code under `memory/freshness/*` that generalises (coordination, decision_engine, metrics, targets) is moved to `src/metatron/freshness/` with re-export shims under `memory/freshness/` to preserve imports. The shims are one-liners; keeping them forever avoids churn on any downstream that `import metatron.memory.freshness.coordination`.

## Acceptance criteria (reviewer checklist, restated testably)

1. `make lint` — zero errors on new and modified files.
2. `make typecheck` — zero errors (mypy strict).
3. `make test` — all new unit tests pass; Phase A tests unchanged.
4. `make test-all` — integration suite passes against live PG + Qdrant + Neo4j + Redis.
5. `make migrate` runs cleanly on empty DB; `alembic downgrade -1 && alembic upgrade head` round-trips.
6. `METATRON_FRESHNESS_ENABLED=false` (default): all existing ingestion + search paths byte-identical to pre-branch. Grep for zero Redis traffic from ingestion when flag off.
7. `METATRON_FRESHNESS_ENABLED=true, METATRON_FRESHNESS_KB_ENABLED=true` + connector sync: worker consumes a KB job end-to-end (verified by integration test — status transition, MachineEvent, Qdrant payload sync, Neo4j edge).
8. `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED=true`: ARCHIVED raw_documents excluded from search results (verified by integration test).
9. `make eval-compare` with filter flag on shows no regression vs. baseline beyond ±0.5 pp nDCG@10 (agreed 2026-04-22).
10. Every PG query, Redis key, and Qdrant filter in new code carries `workspace_id`. Reviewer grep: `grep -rn "workspace_id" src/metatron/ingestion/freshness/ src/metatron/freshness/` hits every file that reads/writes data.
11. No new import from `agent/`, `channels/`, `api/routes/chat.py`, `api/routes/finops.py` into new modules.
12. `interfaces.py` unchanged. `events.py` unchanged. Four existing event names + payload convention preserved.
13. `make test` shows Phase A memory-freshness tests still green (regression guard on stage-adapter refactor).

---
