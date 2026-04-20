# Freshness Worker for Agent Memory (Phase A) — Design

**Date:** 2026-04-20
**Jira:** MTRNIX-304 (Phase A). Split-offs: MTRNIX-313 (KB phase B), MTRNIX-314 (MCP lifecycle surface).
**Epic:** MTRNIX-227 — Agent Memory System (WS1).
**Author:** Konstantin Kuzmin
**Status:** Approved — ready for implementation plan

## Context

Metatron's WS1 agent memory currently persists `MemoryRecord` rows with `{content, tags, importance_score, ttl_expires_at, scope, session_id, metadata}`. There is no lifecycle model — all records are equal, forever. Stale, superseded, or contradictory facts accumulate without any mechanism to demote them. External agents (Hermes) calling `memory_search` get mixed in noise.

The `metamemory` reference project already implemented a freshness worker against its own `KnowledgeItem` model. Phase A of MTRNIX-304 ports that concept **onto the existing metatron-core `MemoryRecord` surface**, scoped to agent memory only. Phase B (MTRNIX-313) extends the same pipeline to the KB side.

Design philosophy is explicit: *autoresearch bounded loops*, not one opaque autonomous agent. Each pipeline stage does one thing, is independently observable, idempotent, pausable, and replayable. This is the opposite of "give an LLM the stale list and ask it to fix things."

## Scope

Phase A only:

- Assertion lifecycle fields on `MemoryRecord`.
- Two new supporting tables (`review_entries`, `machine_events`).
- Redis-backed coordination (queue, locks, checkpoints).
- Five-stage pipeline implementation in `src/metatron/memory/freshness/`.
- Standalone worker process entry-point.
- Observability: structlog + MachineEvent rows + Prometheus metrics.

**Out of scope** (tracked separately):

- KB freshness (MTRNIX-313).
- MCP tool surface for `status` filter + review queue (MTRNIX-314).
- `/v1/chat/completions` memory context injection (MTRNIX-275).
- Control Center UI for the review queue.

## Architecture

### Data model

Extend `MemoryRecord` (in `core/models.py` and corresponding PG schema) with:

| Field | Type | Purpose |
|---|---|---|
| `status` | enum | `CANDIDATE / ACTIVE / STALE / SUPERSEDED / ARCHIVED / CONFLICTED / REVIEW_NEEDED`. Default `CANDIDATE` on first store. |
| `freshness_score` | float [0.0..1.0] | Derived by FreshnessMonitor. `0.0`=archived, `0.1`=superseded, `0.25`=stale, `>=0.5`=active. |
| `superseded_by` | UUID \| null | Points at the replacing record, when known. |
| `valid_from` | timestamptz \| null | Earliest time the fact is considered true. |
| `valid_until` | timestamptz \| null | Expiry. Past `valid_until` → auto-archive. |
| `evidence_count` | int | Number of supporting source artefacts. Curator uses this for CANDIDATE→ACTIVE promotion. |
| `verification_state` | string \| null | Free-form audit label (`connector_materialized`, `pending_review`, `llm_verified`, …). |

New tables:

- `review_entries(id, workspace_id, record_id, reason, related_record_id, content, confidence, created_at)` — flagged items awaiting human / agent resolution.
- `machine_events(id, workspace_id, event_type, actor, target_kind, target_id, payload_json, created_at)` — append-only audit log of every freshness action.

All tables preserve the `workspace_id` isolation rule.

### Coordination (Redis)

Reuse the existing Redis client (session cache backend). Add a thin coordination layer in `src/metatron/memory/freshness/coordination.py`:

- `enqueue_job(job: FreshnessJob)` — LPUSH on `freshness:queue:{workspace_id}` (per-workspace isolation to avoid cross-tenant starvation).
- `dequeue_events(queue, max_items)` — BRPOP with bounded batch.
- `acquire_lock(key, ttl_seconds)` / `heartbeat(key, ttl)` / `release(key)` — SET NX EX + periodic extension. Locks are **per-stage-per-item** so Linker and Reconciler on different items can run in parallel, but two workers cannot race on the same `freshness:linker:<record_id>` key.
- `write_checkpoint(key, value)` — per-stage last-completion marker, used for idempotent re-runs.

### Pipeline stages

Each stage lives in its own module under `src/metatron/memory/freshness/`, takes a `MemoryService` handle, acquires its lock, heartbeats, writes a checkpoint.

1. **Linker** (`linker.py`) — search Qdrant/Neo4j for related records (cosine > 0.6), update `evidence_count`, draw edges in Neo4j. Uses the existing metatron-core Qdrant client — we do NOT reintroduce metamemory's custom `EmbeddingProvider` abstraction.
2. **Reconciler** (`reconciler.py`) — detect near-duplicates (cosine > 0.85) or exact-match collisions within workspace. Create `ReviewEntry` with `reason="possible_duplicate"` (or `"possible_contradiction"` when the DecisionEngine flags a contradiction later). Add `ALIAS` edge in Neo4j. Never auto-merges or auto-deletes.
3. **FreshnessMonitor** (`monitor.py`) — rule engine on time / supersession:
   - `valid_until <= now` → ARCHIVED, `freshness_score=0.0`
   - `superseded_by` resolves to an existing record → SUPERSEDED, `0.1`
   - `updated_at > 30d` (configurable `FRESHNESS_STALE_AFTER_DAYS`) → STALE, `0.25`
4. **Curator** (`curator.py`) — only safe, deterministic promotions. Today: `CANDIDATE` with `evidence_count >= 1` → `ACTIVE`. Always adds the `auto_curated` tag for traceability.
5. **DecisionEngine** (`decision_engine.py`) — the single LLM-touching stage. Protocol-based:
   - `RuleBasedDecisionEngine` — keyword fallback, confidence `0.55` (always routes to review).
   - `OpenAICompatibleDecisionEngine` — calls local Ollama endpoint with the agreed SLMs (`qwen2.5-4b-instruct-q4` or `gemma-4-e4b-q4`), strict JSON response schema: `{action, confidence, tags, entities, rationale}`.
   - Decisions with `confidence >= FRESHNESS_DECISION_CONFIDENCE_THRESHOLD` (default `0.7`) are auto-applied. Below threshold → `ReviewEntry` with `reason="low_confidence_decision"`.

### Worker process

`src/metatron/memory/freshness/worker.py` + entry-point `python -m metatron.memory.freshness`.

- Bounded loop: `run_once(max_jobs=20)`. Empty queue → sleep `FRESHNESS_POLL_SECONDS` (default `2.0`).
- Exponential backoff on errors: base `2s`, max `60s`, hard exit after `10` consecutive failures.
- Structured logging (structlog JSON in prod, colored in dev).
- Runs as a separate process from the API — no HTTP interface. Added to `docker-compose.yml` as an optional service.

### Job producers

- `memory_store` MCP tool → after successful PG write, `enqueue_job({kind="memory_record", id=…, event_type="knowledge_changed"})`.
- `memory_batch_store` → one job per stored record.
- `memory_update` → enqueue job with `event_type="content_changed"` when `content` mutates.
- Scheduled scan (future, can be added in MTRNIX-313 or a follow-up): nightly enqueue of `updated_at > 30d` records to let the FreshnessMonitor demote them even without an event.

## Layer boundaries

- Freshness code lives in `src/metatron/memory/freshness/` — an **L3** submodule of `memory/`. Can import from `core/` (L0), `storage/` (L1), `llm/` (L3, sibling).
- Must not import from `agent/`, `channels/`, `api/`.
- Worker entry point is separate from API — no FastAPI routes added for the worker itself.

## Config (env vars, `METATRON_` prefix)

- `FRESHNESS_ENABLED` (default `false` on Phase A — feature flag while we tune SLMs)
- `FRESHNESS_POLL_SECONDS` (default `2.0`)
- `FRESHNESS_MAX_JOBS_PER_ITERATION` (default `20`)
- `FRESHNESS_LOCK_TTL_SECONDS` (default `30`)
- `FRESHNESS_STALE_AFTER_DAYS` (default `30`)
- `FRESHNESS_DECISION_CONFIDENCE_THRESHOLD` (default `0.7`)
- `FRESHNESS_LLM_MODEL` (default `qwen2.5-4b-instruct-q4`)
- `FRESHNESS_LLM_API_BASE_URL` (default: existing `OLLAMA_BASE_URL`)
- `FRESHNESS_LLM_API_KEY` (default empty — Ollama has no auth)
- `FRESHNESS_LINKER_THRESHOLD` (default `0.6`)
- `FRESHNESS_RECONCILER_THRESHOLD` (default `0.85`)

## Observability

- **structlog events:** `worker_start`, `worker_exit`, `queue_poll`, `stage_start`, `stage_end`, `stage_error`, `decision_made`.
- **MachineEvents in PG:** `freshness_job_received`, `freshness_job_processed`, `freshness_job_skipped`, `freshness_stage_completed`, `freshness_decision_made` (full payload), `freshness_worker_heartbeat`.
- **Prometheus metrics:**
  - `freshness_jobs_total{status}` — counter
  - `freshness_queue_depth` — gauge (per workspace)
  - `freshness_stage_duration_seconds{stage}` — histogram
  - `freshness_decision_confidence` — histogram (0.0–1.0)
  - `freshness_worker_errors_total{stage}` — counter

## Testing

Unit tests (tests/unit/memory/freshness/):

- Each stage tested in isolation with mocked stores.
- DecisionEngine: JSON parsing happy path, malformed-JSON fallback, below-threshold → review entry.
- Worker: single-iteration loop, empty queue, backoff escalation, hard-exit path.
- Coordination: lock re-entry, checkpoint write, BRPOP batch boundary.

Integration tests (tests/integration/memory/freshness/):

- End-to-end: enqueue a `knowledge_changed` job, run worker, assert PG status transition + MachineEvent rows + Qdrant payload refresh.
- Reconciler duplicate detection against a live Qdrant collection.

## Migration & rollout

- Alembic migration adds the new columns with `DEFAULT` values so existing rows land as `ACTIVE / freshness_score=0.5`.
- Feature flag `FRESHNESS_ENABLED=false` initially — no worker process started in prod until the Sergey's bench-off confirms SLM choice.
- `memory_search` is NOT status-aware yet (MTRNIX-314) — archived records remain reachable by search until that ticket lands. Acceptable for the feature-flag-off period.

## Resolved trade-offs

Three design questions were considered and resolved before kicking off the implementation plan. Each is recorded here so the Architect does not re-open them.

### 1. Extend `MemoryRecord` in place vs. introduce an `Assertion` wrapper

**Decision: extend `MemoryRecord` in place.**

Rationale — introducing an `Assertion` wrapper in Phase A is premature abstraction. The existing memory MCP tools (`memory_store`, `memory_search`, `memory_list`, …) and the `MemoryService` public surface would have to be refactored twice — once to wrap, and possibly again if Phase B shows KB needs a different shape. Deferring the wrapper-vs-inline decision keeps blast radius small.

Consequence — `MemoryRecord` grows seven new fields (`status`, `freshness_score`, `superseded_by`, `valid_from`, `valid_until`, `evidence_count`, `verification_state`). All existing callers continue to work because defaults are backwards-compatible (`status=ACTIVE`, `freshness_score=0.5`, the rest `null/0`). If Phase B (MTRNIX-313) shows that KB needs a genuinely different lifecycle, we introduce an `Assertion` protocol then — at that point both shapes are on the table and the trade-off is concrete.

### 2. Queue topology — per-workspace vs. single shared

**Decision: per-workspace queue, keyed `freshness:queue:{workspace_id}`.**

Rationale — metatron-arch-guard critical rule #3 ("Every data operation MUST be workspace-scoped") applies to data-flow primitives, not just storage. A single shared queue allows one workspace's backlog to starve another's freshness job processing. Per-workspace keys cost an irrelevant amount of Redis memory (one LIST key per active workspace) and give natural scaling: dedicated workers per workspace if and when the shape of the load demands it.

Consequence — the worker's `dequeue_events` call rotates through a known set of workspace keys (enumerated from PG `workspaces` table on each iteration) and reads a bounded slice from each. Queue-depth metric is emitted per-workspace; aggregate dashboards sum across workspaces.

### 3. LLM integration for DecisionEngine — reuse `llm/provider.py` vs. direct Ollama

**Decision: reuse `llm/provider.py`.**

Rationale — metatron-core already supports `ollama | deepseek | openrouter | custom` providers via the `METATRON_LLM_PROVIDER` machinery. Hard-coding Ollama in DecisionEngine would lock freshness to a single deployment shape and break the Control Center / enterprise deployments that run OpenRouter or a shared DeepSeek endpoint. Structured-JSON handling is a thin concern — the DecisionEngine parses the provider's response string as JSON and falls back to the rule-based engine on any parse error or malformed payload.

Consequence — DecisionEngine receives a provider instance via DI. Config vars (`FRESHNESS_LLM_MODEL`, `FRESHNESS_LLM_API_BASE_URL`, `FRESHNESS_LLM_API_KEY`) are read by a small factory that builds a dedicated provider independent of the main chat LLM (`METATRON_LLM_MODEL`). The `RuleBasedDecisionEngine` remains as a fallback and as the default when `FRESHNESS_LLM_API_BASE_URL` is empty.
