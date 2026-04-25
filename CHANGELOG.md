# Changelog

## [Unreleased]

### Added
- test: OAI-compat integration smoke (MTRNIX-323 §4). One full
  `create_app(...)` + `TestClient` round-trip against
  `POST /v1/chat/completions` validates the wiring (200 + citations
  rendered as markdown links + non-ASCII Russian query path) that
  unit-level tests can't catch — the failure mode is `create_app`
  drift or `hybrid_search_and_answer` returning a body the OAI
  envelope can't parse. Lives at
  `tests/integration/api/test_openai_compat_smoke.py`.

### Changed
- breaking (REST): `POST /api/v1/agents/{id}/start|stop|pause` on an
  `ARCHIVED` agent now returns 400 (`AgentInvalidStateTransitionError`)
  instead of un-archiving the agent. The new
  `POST /api/v1/agents/{id}/restore` (editor+) is the only transition
  out of ARCHIVED, and it lands in STOPPED — operators must explicitly
  `/start` afterwards. Per MTRNIX-319 §5, no live consumer was relying
  on the previous un-delete loophole. The full lifecycle×status matrix
  is enforced by `_ALLOWED_LIFECYCLE_SOURCES` in
  `agents/service.py`. (MTRNIX-323)
- chore: Eval dataset v1.3 → v1.4 (MTRNIX-323 §2). Four
  temporal/status queries (`exec-02`, `time-01`, `time-03`, `ru-02`)
  rewritten to topic-anchored form so they no longer drift as Jira
  tickets transition to Done; two sprint-anchored queries (`time-05`,
  `agg-01`) flagged `stable: false` until sprint metadata lands in
  the retrievable payload. Aggregate metrics on the queries that
  exist in both v1.3 and v1.4 stay within ±0.01.

### Fixed
- fix: KB freshness sync_downstream_stores resolves UUID → source_id
  (MTRNIX-313 follow-up, PR #95). `RawDocumentTarget.sync_downstream_stores`
  was passing the freshness job's `target_id` (raw_documents.id UUID)
  directly to `update_payload_by_doc_label` and
  `set_raw_document_status`. Both downstream stores key by
  `doc_label = raw_documents.source_id` (Confluence page id, Jira issue
  key) — UUID never matched a real chunk or `:Document` node, so every
  worker-driven KB lifecycle transition was a silent no-op on Qdrant
  and Neo4j. Net effect: `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED=true`
  was useless before this fix; the retrieval `must_not` filter had
  nothing to filter because Qdrant payloads never received the
  lifecycle status. Surfaced during MTRNIX-319 ad-hoc KB validation.
  Fix fetches the raw_document, extracts source_id, uses it as the
  doc_label argument. End-to-end validation: doc-02 query MRR 1.000 →
  0.000 when the expected document is transitioned to ARCHIVED.
- fix: Eval driver event-loop reuse (MTRNIX-323 §1). `scripts/run_eval.py`
  now wraps the entire run in a single `asyncio.run()`, calling
  `clear_store_cache()` immediately before to flush any stray async
  Qdrant client an import-time side effect may have parked on a
  different loop. Previously the per-query
  `hybrid_search_and_answer_sync` calls each created and closed their
  own loop, leaving the cached `AsyncQdrantVectorStore` bound to a
  closed loop and forcing 8/29 queries through the
  `qdrant.async.hybrid_search.fallback` dense-only path. Three
  consecutive `make eval` runs now emit 0 fallback events.

### Added
- feat: Freshness queue reliability — processing-list reclaim + scheduled-scan
  safety net + env-prefixed Redis keys close the Phase A pre-prod gaps
  (MTRNIX-316). **Requires Redis >= 6.2 for `LMOVE`.** The worker no longer
  loses jobs on a SIGKILL mid-batch: each worker claims a unique
  `worker_id = {hostname}:{pid}:{short-uuid}` at bootstrap and moves
  dequeued jobs into its own `freshness:{env}:processing:{worker_id}` list
  via `LMOVE`. A heartbeat key (`freshness:{env}:heartbeat:{worker_id}`,
  TTL 20s) plus a per-workspace reclaim pass (every
  `METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS`, default 30 iterations)
  drains any dead peer's processing list back to the main queue. A
  scheduled-scan safety net (memory only in this ticket; KB deferred)
  periodically enqueues freshness jobs for records that never received
  a write-triggered event. Every freshness Redis key is now namespaced
  by `METATRON_ENV` so dev rigs sharing a Redis instance can't collide;
  legacy unprefixed keys are opportunistically drained at startup when
  `METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP=true`. Six new settings:
  `METATRON_FRESHNESS_HEARTBEAT_TTL_SECONDS` (20),
  `METATRON_FRESHNESS_RECLAIM_INTERVAL_ITERATIONS` (30),
  `METATRON_FRESHNESS_SCHEDULED_SCAN_ENABLED` (True),
  `METATRON_FRESHNESS_SCHEDULED_SCAN_INTERVAL_SECONDS` (3600),
  `METATRON_FRESHNESS_SCAN_BATCH_LIMIT` (500),
  `METATRON_FRESHNESS_DRAIN_LEGACY_AT_STARTUP` (False). Five new
  Prometheus counters: `freshness_orphans_reclaimed_total`,
  `freshness_reclaim_errors_total`,
  `freshness_scheduled_scan_jobs_enqueued_total`,
  `freshness_scheduled_scan_errors_total`,
  `freshness_legacy_keys_drained_total`. Backwards-compatible when
  `METATRON_ENV` is unset — the key shape is byte-identical to Phase A.
- chore: Pre-rollout validation gate closed (MTRNIX-319). Eval dataset
  v1.3 refreshes 11 Confluence doc_label IDs that drifted to new
  page IDs after a workspace reorg — restored measurable retrieval
  quality (P@10 0.05 → 0.14, MRR 0.26 → 0.63, NDCG 0.22 → 0.58).
  New onboarding doc `docs/ROLLOUT_NOTES_2026-04-24.md` for teams
  picking up the project. Remaining loose ends (eval event-loop flake,
  temporal-query hygiene, Agent Registry UX, optional OAI smoke)
  tracked as MTRNIX-323.

### Fixed
- fix: `MemoryService.resolve_review` is now atomic across its three
  PG writes (MTRNIX-319, PR #89). Previously each of update_lifecycle /
  delete_review_entry / save_machine_event ran in its own
  `engine.begin()` transaction — a failure on the third left the first
  two committed while the caller received an error. Added
  `MemoryPostgresStore.begin()` + optional `conn` kwarg on the three
  store methods; the service now opens one transaction and threads
  the connection through. Same PR also fixes misleading error
  bucketing: DB-error exceptions (`DBAPIError`, `OperationalError`,
  `UntranslatableCharacterError`, etc.) no longer get bucketed as
  `WORKSPACE_NOT_FOUND` based on the SQL text containing
  `workspace_id`. 14 new unit tests.

### Added
- feat: Freshness worker syncs memory Qdrant status payload on every
  lifecycle transition (MTRNIX-322). `MemoryTarget.sync_downstream_stores`
  now writes `{"status": status.value}` onto the per-workspace Qdrant
  point via `update_payload` — previously a deliberate no-op. Hook is
  called by `FreshnessMonitor` (already wired in MTRNIX-313), `Curator`
  CANDIDATE → ACTIVE promotion, and `apply_decision` mark_stale branch.
  Closes the drift between PG `memory_records.status` and the Qdrant
  payload that leaked non-ACTIVE records through `memory_search` under
  the default `status=["active"]` filter. Adds Prometheus counter
  `freshness_qdrant_sync_failed_total{target_kind,stage}` for
  observability. Best-effort — Qdrant failures are logged at WARNING
  and counted, never propagate. PG remains source of truth; the
  `scripts/backfill_memory_qdrant_status_payload.py` script stays as
  the long-tail safety net. No migration, no new config flags.
- feat: Memory MCP lifecycle-status filter + review queue tools (MTRNIX-314).
  `memory_search` and `memory_list` now accept a `status` param (default
  `["active"]`, pass `["all"]` to disable). Two new MCP tools —
  `memory_review_list` and `memory_review_resolve` — let external agents
  paginate and act on the freshness pipeline's review queue. `resolve_review`
  is soft-only: `keep` → ACTIVE, `archive` → ARCHIVED, `merge_into:<id>` →
  SUPERSEDED, `discard` → ARCHIVED. Emits a `freshness_review_resolved`
  MachineEvent and (when wired) a `FRESHNESS_REVIEW_RESOLVED` EventBus event.
  No migration, no config flags.
- feat: KB freshness worker (Phase B, MTRNIX-313) — extends the freshness pipeline to `raw_documents`. Generalises stages via `FreshnessTarget` protocol with `MemoryTarget` + `RawDocumentTarget` adapters. Adds 7 lifecycle columns to `raw_documents` (migration 018), retrieval-side ARCHIVED filter pushdown (flag-gated), freshness scoring signal (weight default 0.0 → math identical). 3 new env vars: `METATRON_FRESHNESS_KB_ENABLED`, `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED`, `METATRON_FRESHNESS_WEIGHT`. Worker dispatches by `target_kind`. `review_entries.record_id` renamed to `target_id` + new `target_kind` column (Phase A subscribers preserved via dataclass alias).
- feat: freshness worker for agent memory (Phase A, MTRNIX-304) — 5-stage bounded-loop pipeline (Linker → Reconciler → FreshnessMonitor → Curator → DecisionEngine), per-workspace Redis queue, standalone worker process. Feature-flagged via `METATRON_FRESHNESS_ENABLED` (default false). Adds 7 lifecycle fields to `memory_records` + `review_entries` + `machine_events` tables (migration 016). Follow-ups: MTRNIX-313 (KB Phase B), MTRNIX-314 (MCP status filter + review queue), MTRNIX-316 (queue reliability pre-prod gate).
- MCP tools: `metatron_memory_search`, `metatron_memory_store`, `metatron_memory_delete` for agent memory CRUD via MCP (MTRNIX-303).
- MCP tool: `metatron_search_fast` — low-latency document lookup (dense + optional metadata, P50 <800 ms target) (MTRNIX-303).
- `fast_search()` function in `retrieval/search.py` — bypasses reranker / HyDE / query expansion / graph / LLM answer generation.
- Config: `METATRON_SEARCH_FAST_TOP_K`, `METATRON_SEARCH_FAST_INCLUDE_METADATA`.

### Changed
- `MemoryService` moved from `src/metatron/agent/memory_service.py` (L4) to `src/metatron/memory/service.py` (L3) — correct layering. Backward-compat shim left at the old location; existing `from metatron.agent.memory_service import MemoryService` imports keep working.
- `docs/HERMES_INTEGRATION.md` — added "Routing patterns" section, updated tool table to 9 tools, removed stale "Memory tools not exposed via MCP" gap note.

- feat: WS1 Stage 1 — core memory models and interfaces (MTRNIX-240)
- feat: memory hybrid search service (`MemorySearchService`) combining Qdrant vector, Neo4j graph, and Redis session legs with weighted blend and graceful degradation (MTRNIX-247)
- feat: memory REST API endpoints (`POST /api/v1/memory/records`, `POST /api/v1/memory/search`, `GET /api/v1/memory/records`, `DELETE /api/v1/memory/records/{id}`) with workspace scope, RBAC, and full CRUD integration test (MTRNIX-248)
- **Breaking**: Replace Memgraph with Neo4j Community Edition for knowledge graph storage
  - Docker image: `memgraph/memgraph:2.18.1` → `neo4j:5-community`
  - Env vars: `MEMGRAPH_*` → `NEO4J_*` (old names still work via aliases)
  - Internal: `storage/memgraph.py` → `storage/neo4j_graph.py`, all functions renamed
  - Cypher queries migrated from inline `_esc()` escaping to `$param` parameterized queries
  - Removed Memgraph write-lock (Neo4j handles concurrent read/write)
  - Removed Cypher syntax workarounds (keyword collisions, backtick escaping)
  - API: `/ready` response key changed from `memgraph` to `neo4j`
  - API: `/admin/status` response key changed from `memgraph` to `neo4j`
- feat: add Redis local dev setup — docker-compose, config, async storage client
- feat: activate root-child hierarchical chunking (MTRNIX-210)
- fix: auto-create Qdrant collection before ingestion (prevents 404 after cleanup)
- feat: graph-rebuild script for Memgraph recovery (`make graph-rebuild`)
- feat: retry failed graph writes after parallel extraction
- fix: deduplicate eval P@K by doc_label (removes inflated metrics from duplicate chunks)
- fix: verify Memgraph connection liveness before reuse (eliminates 30s timeout on defunct connections)
- fix: reduce GRAPH_EXTRACTION_WORKERS default to 1 (prevents Memgraph transaction conflicts)
- feat: clear graph entity cache on SYNC_COMPLETED event
- feat: two-phase grid search with caching — reduces runtime from months to minutes (MTRNIX-261)
- fix: update eval testset with current data (stale expected docs)
- feat: platform user mapping for Telegram/Slack/Discord channels (MTRNIX-263)
- feat: admin CRUD API for platform user mappings
- feat: AsyncQdrantVectorStore for async Qdrant access (MTRNIX-262 Phase 1)
- feat: async retrieval pipeline with parallel recall channels (MTRNIX-262 Phase 2)
- feat: async ingestion pipeline with AsyncQdrantVectorStore (MTRNIX-262 Phase 3)
- feat: document store layer — PostgreSQL as source of truth for ingestion (MTRNIX-265)
- feat: decouple graph extraction from sync — process from PostgreSQL separately (MTRNIX-266)
- feat: adaptive RRF fusion constant based on dense/sparse overlap (MTRNIX-211, default off — needs tuning)
- feat: transitive alias resolution via graph — 1..3 hop BFS over ALIAS edges (MTRNIX-212)
- feat: persistent deduplication index — SimHash fingerprints in PostgreSQL (MTRNIX-213)
- feat: push temporal filtering into Cypher queries + Memgraph indexes (MTRNIX-214)
- feat: HyDE for short/vague queries — hypothetical document embeddings (MTRNIX-215, default off)
- feat: SPLADE learned sparse representations replacing BM25 (MTRNIX-216)
- feat: SPLADE refactored into standalone microservice (MTRNIX-216 Phase 2)
