# CLAUDE.md — Metatron Core

## What is this
Metatron Core (MTRNIX) — open-source memory + knowledge infrastructure for AI agents. Provides hybrid RAG over corporate documents AND persistent agent memory (WS1) through three consumer surfaces:

- **MCP server** — primary integration path for agent runtimes (Hermes, Cursor, Claude Desktop, custom MCP clients)
- **OpenAI-compatible API** (`/v1/chat/completions`) — for OpenWebUI, LibreChat and any OAI client
- **REST API** (`/api/v1/*`) — raw access to documents, memory, workspaces, connectors

Python 3.12+, FastAPI + asyncio. Product transitioned (2026-04) from "enterprise corporate KB" to open-core memory infra for AI-native companies. Commercial Control Center (separate repo, planned) layers agent registry, workflow, governance and observability on top.

See `docs/HERMES_INTEGRATION.md` for the recommended external-agent setup and `docs/LEGACY.md` for modules being phased out.

## Quick Commands
```
make dev              # uvicorn --reload on :8000
make test             # pytest (unit only, no live services)
make test-all         # pytest (including integration)
make lint             # ruff check + format --check
make format           # ruff check --fix + format
make typecheck        # mypy src/metatron/
make migrate          # alembic upgrade head
make migrate-new name="description"
make docker-up        # start postgres + qdrant + neo4j
make docker-down
make eval             # run search quality eval (needs live services)
make eval-compare     # run eval + compare with last saved result
make grid-search-cache # cache recall+reranker scores for grid search (~12 min)
make grid-search      # grid search for optimal scoring weights (uses cache, fast)
make grid-search-fine # grid search with finer step (0.05)
make graph-rebuild    # rebuild Neo4j graph from PG raw_documents (after graph loss)
make graph-rebuild-dry # preview what graph-rebuild would process
make graph-process    # process unsynced documents for graph extraction
```

Direct commands:
```
python -m metatron          # API + legacy channel bots (Telegram/Discord/Slack) — channels scheduled for removal
python -m metatron.api.app  # API only — preferred entry for new deployments
python -m metatron.mcp      # MCP server (stdio/streamable-http) — for Hermes / Cursor / Claude Desktop
python -m metatron.memory.freshness  # run freshness worker (requires METATRON_FRESHNESS_ENABLED=true)
pytest tests/unit/test_search.py::test_name -v  # single test
```

## Architecture (6 layers — strict one-way dependencies, never import upward)
```
L6  api/            REST + OAI-compat + MCP HTTP mount (FastAPI routes, middleware)
L5  channels/       [LEGACY] Telegram, Discord, Slack bots — moving out, do NOT extend
L4  agent/          Intent router, commands, executor (memory_service now a shim -> memory/service.py)
L3  services        connectors/, llm/, mcp/, memory/, auth/, workspaces/, agents/
                    [INACTIVE] skills/ — engine unimplemented, kept as reserved capability
L2  processing      ingestion/, retrieval/
                    [OPTIONAL] benchmarker/ — dev-eval tool, may move out of core
L1  storage/        PostgreSQL, Qdrant, Neo4j, Redis clients (no business logic)
L0  core/           Config, Interfaces, Models, Events, Plugin (ZERO upward deps)
```

`memory/` (L3) is the first-class new module built in WS1. See `src/metatron/memory/.claude/CLAUDE.md`.
Legacy markers reflect the 2026-04 product transition — details and migration plan in `docs/LEGACY.md`.

`freshness/` (L3) is a shared submodule (promoted from `memory/freshness/` in MTRNIX-313) — the
5-stage pipeline (Linker → Reconciler → FreshnessMonitor → Curator → DecisionEngine),
`CoordinationStore`, `apply_decision`, and metrics are generic over a `FreshnessTarget`
adapter protocol. Concrete adapters live at `memory/freshness/target_memory.py` (agent memory)
and `ingestion/freshness/target_raw_document.py` (KB raw_documents). A single worker process
hosts both pipelines and routes jobs by `target_kind`.

## Source Layout
```
src/metatron/
├── app.py                    # Unified entry: asyncio.gather(API + bots)
├── api/
│   ├── app.py                # create_app() factory, lifespan, plugin discovery
│   ├── middleware.py          # OptionalAuthMiddleware (JWT gate)
│   ├── dependencies.py        # FastAPI DI helpers
│   └── routes/                # auth, chat, admin, skills, connections, documents,
│                              # workspaces, sync, benchmarker, dashboard/, files (+ download), graph, health
├── auth/
│   ├── jwt.py                 # HS256, create_token/verify_token, 24h default
│   ├── rbac.py                # Role hierarchy: viewer(0) < editor(1) < admin(2)
│   ├── dependencies.py        # get_current_user → plugin auth → fallback JWT
│   ├── user_mapping.py        # Platform identity → internal User (Telegram/Slack/Discord)
│   └── user_store.py          # User CRUD against PostgreSQL
├── core/                      # L0 — ZERO dependencies on anything above
│   ├── config.py              # Settings (pydantic-settings), all METATRON_* env vars
│   ├── interfaces.py          # ABCs: Connector, Channel, LLM, VectorStore, GraphStore,
│   │                          #   Processor, AuthBackend, Retriever
│   │                          # Protocols: EventHandler, PipelineHook
│   ├── models.py              # Dataclasses: Document, Chunk, User, Role, Skill, etc.
│   ├── plugin.py              # PluginManager, MetatronPlugin protocol, discover_plugins()
│   ├── events.py              # EventBus (async pub/sub), event constants
│   ├── exceptions.py          # MetatronError → ConnectorError, AuthenticationError, etc.
│   ├── http.py, logging.py, utils.py
│   └── __init__.py
├── agent/                     # L4 — router.py, sessions.py (legacy), commands.py, executor.py
│                              #   memory_service.py = backward-compat shim re-exporting memory/service.py
├── channels/                  # L5 — [LEGACY] telegram.py, discord.py, slack.py, manager.py (to be extracted)
├── connectors/                # L3 — confluence, jira, notion, github, gdrive, slack_history, files
│   └── registry.py            # Connector registry (independent from PluginManager)
├── ingestion/                 # L2 — pipeline.py, chunking.py, dedup.py, bm25.py, splade.py, sync.py
│   ├── processors/            # pdf, html, office, text, tabular, dates, titles, translation
│   └── freshness/             # [MTRNIX-313] KB adapter site — producer.py (connector-sync hook)
│                              #   + target_raw_document.py (RawDocumentTarget)
├── llm/                       # L3 — provider.py, embeddings.py, base.py
│   └── providers/             # ollama, deepseek, openrouter, custom
├── mcp/                       # L3 — server.py, client.py, adapter.py, registry.py
│   └── tools/                 # search, sync, get, store, status
├── retrieval/                 # L2 — search.py, channels.py, scoring.py, query_classifier.py,
│                              #   hybrid.py, query_expansion.py, reranker.py, token_budget.py,
│                              #   fallback.py, graph_enrichment.py, aliases.py, alias_registry.py
├── storage/                   # L1 — postgres.py, qdrant.py (sync+async), neo4j_graph.py, encryption.py
├── observability/             # health.py, metrics.py, tracer.py
├── workspaces/                # L3 — manager.py, models.py, persistence.py (current "KB tenant" model; future agent-scoped)
├── skills/                    # L3 — [INACTIVE] engine.py — NotImplementedError; reserved for future declarative tool docs
├── memory/                    # L3 — service.py (MemoryService orchestration, PG source of truth),
│                              #   search.py (hybrid MemorySearchService), serde.py (Qdrant payload deserializer)
│                              #   First-class new module (WS1). Assertion lifecycle layer planned on top.
│   └── freshness/             # [MTRNIX-304 / MTRNIX-313] memory adapter site — producer.py,
│                              #   target_memory.py (MemoryTarget), worker.py, __main__.py.
│                              #   Shared stage code lives in `freshness/` (top-level).
├── freshness/                 # L3 — [MTRNIX-313] shared freshness pipeline (promoted from
│                              #   memory/freshness/): stages/ (linker, reconciler, monitor,
│                              #   curator), coordination.py, decision_engine.py, apply_decision.py,
│                              #   metrics.py, targets.py (FreshnessTarget protocol).
├── agents/                    # L3 — Agent Registry (WS4, MTRNIX-270): models.py (AgentRecord,
│                              #   AgentStatus), service.py (AgentRegistryService), persistence.py
│                              #   (PG store). CRUD + lifecycle flag + versioned config. Hermes
│                              #   agent identity. Governance/5-role RBAC deferred to CC plugin.
├── benchmarker/               # L2 — [OPTIONAL] api/, db/, schemas/, services/metrics/ — dev eval tool
└── scripts/                   # graph_audit.py, run_eval.py, grid_search_weights.py,
                               # graph_rebuild.py, graph_process.py
```

## Plugin System
Enterprise extensions hook into core via Python entry points:
```toml
# In enterprise's pyproject.toml:
[project.entry-points."metatron.plugins"]
enterprise = "metatron_enterprise.plugin:EnterprisePlugin"
```

Core discovers plugins at startup in `create_app()`:
```
create_app() → PluginManager() → discover_plugins() → plugin.register(manager)
→ apply middlewares → include core routes → include plugin routes
```

Extension points in PluginManager:
- `register_auth_provider()` — replaces default JWT auth
- `register_middleware()` — adds FastAPI middleware
- `register_event_handler()` — subscribes to EventBus events
- `register_routes()` — adds API routers
- `register_pipeline_hook()` — hooks into search/ingestion pipeline
- `register_sso_provider()` — SSO providers

If no plugins installed — core works exactly as before.

## Event Bus
Constants in `core/events.py`: DOCUMENT_INDEXED, QUERY_EXECUTED, CHUNK_CREATED, USER_AUTHENTICATED, SYNC_STARTED, SYNC_COMPLETED, SYNC_FAILED.

EventBus is fault-tolerant — a failing handler is logged and skipped, others continue.

Core event subscriptions (wired in `create_app()`):
- `SYNC_COMPLETED` → `retrieval/channels.py:on_sync_completed()` — clears graph entity LRU cache

## Auth Flow
```
Request → OptionalAuthMiddleware (if AUTH_ENABLED)
→ auth/dependencies.py: get_current_user()
  → 1. Check plugin_manager.get_auth_provider()
  → 2. Fallback: jwt.verify_token()
→ require_admin() / require_editor() / require_viewer() check role level
```

## Search Pipeline
```
Query → [HyDE (optional, short/vague queries)] → expansion → classify(profile) → weight_preset
     → recall_dense + recall_exact + recall_metadata + recall_graph  (parallel via asyncio.gather)
     → merge_channels → compute_signal_score(6 weighted signals, normalized [0,1])
     → top-35 pool → cross-encoder rerank (bge-reranker-v2-m3)
     → compute_final_score(blend: 30% signal + 70% reranker)
     → _prepend_root_context (fetch root chunks for child results, prepend as context)
     → _collect_frags(dict) → _mark_evidence_role(PRIMARY/SUPPORTING)
     → _build_ctx(grouped markdown) → LLM(evidence rules) → _append_sources → answer

Pipeline is fully async (hybrid_search_and_answer is async def).
Recall channels have both sync and async variants; async versions use asyncio.gather.

Sparse search: SPLADE learned representations (default ON) replace BM25 for sparse vectors.
When SPLADE_ENABLED=false, falls back to BM25.

HyDE: for short/vague queries (<=HYDE_MAX_WORDS words), generates hypothetical document
via LLM and embeds it for dense search. Feature flag HYDE_ENABLED (default OFF).

Adaptive RRF: adjusts rrf_k based on dense/sparse overlap ratio. Feature flag
ADAPTIVE_RRF_ENABLED (default OFF — regresses metrics in current eval).

Transitive alias resolution: recall_graph resolves entity aliases via 1..3 hop BFS
over ALIAS edges in Neo4j before entity-based document retrieval.

Scoring signals: dense, graph, metadata, recency, source_balance (smooth gradient).
Weights configurable per query profile (execution, documentation, user_file, relationship, temporal, mixed).
Grid search script: `make grid-search` for weight optimization (two-phase with caching).

Source citation format: `"{icon} {title} — {url}"` (em-dash separator).
Icons: 📄 confluence, 📋 jira, 📎 upload, 📓 notion.
Frontend splits on `" — "` to extract URL; no URL → title only.
```

## Databases
- **PostgreSQL 16** — metadata, users, raw_documents (source of truth), dedup_fingerprints, user_platform_mappings, BM25 index, logs (port 5432)
- **Qdrant v1.16** — vector embeddings 768-dim, SPLADE sparse vectors (port 6333/6334)
- **Neo4j CE v5** — knowledge graph Document→Chunk→Entity, ALIAS edges for transitive resolution (port 7687 bolt, 7474 browser)
- **Ollama** (optional) — local LLM + embeddings (port 11434)

Document flow: Connector → PostgreSQL (raw_documents) → Qdrant + Neo4j.
PostgreSQL raw_documents table is the source of truth; Qdrant/Neo4j are derived stores.
Graph extraction is decoupled from sync (process_all_unsynced_graphs, graph-process CLI).

## Key Config (env vars, prefix METATRON_)
- AUTH_ENABLED (false) — JWT gate on /api/v1/*
- LLM_PROVIDER (ollama) — ollama|deepseek|openrouter|custom
- RERANKER_ENABLED (true) — bge-reranker-v2-m3
- QUERY_EXPANSION_ENABLED (true) — LLM query expansion
- GRAPH_EXTRACTION_ENABLED (true) — NER → Neo4j
- GRAPH_EXTRACTION_WORKERS (1) — parallel workers for graph extraction
- QUERY_CLASSIFIER_ENABLED (true) — hybrid rule+LLM query classifier
- HIERARCHICAL_CHUNKING_ENABLED (true) — root-child chunking in ingestion pipeline
- ADAPTIVE_RRF_ENABLED (false) — adaptive RRF fusion (regresses metrics, off by default)
- RRF_K_LOW (20), RRF_K_HIGH (80) — adaptive RRF k range
- RRF_OVERLAP_THRESHOLD_LOW (0.2), RRF_OVERLAP_THRESHOLD_HIGH (0.7) — adaptive RRF overlap thresholds
- HYDE_ENABLED (false) — HyDE for short/vague queries
- HYDE_MAX_WORDS (4) — max query word count to trigger HyDE
- HYDE_TIMEOUT (8) — HyDE LLM timeout in seconds
- SPLADE_ENABLED (true) — SPLADE learned sparse representations (replaces BM25)
- SPLADE_MODEL (naver/splade-cocondenser-ensembledistil) — SPLADE model name
- SPLADE_MAX_LENGTH (256) — max token length for SPLADE encoding
- DENSE_WEIGHT (0.35), GRAPH_WEIGHT (0.15), METADATA_WEIGHT (0.20), RECENCY_WEIGHT (0.10), BALANCE_WEIGHT (0.05), BLEND_WEIGHT (0.3) — scoring formula weights
- RERANK_POOL_SIZE (35) — candidates sent to cross-encoder
- MIN_SIGNAL_SCORE (0.0) — confidence threshold (0=disabled)
- METATRON_OPENAI_COMPAT_ENABLED (true) — OpenAI-compatible API for OpenWebUI / LibreChat / Hermes OAI mode
- METATRON_OPENAI_COMPAT_KEY ("") — static API key for OpenAI-compat endpoints (Home scenario)
- METATRON_MCP_API_KEY ("") — bearer token for MCP endpoint auth (required for Hermes/Cursor/OpenClaw integration)
- METATRON_OPENWEBUI_URL ("") — bundled OpenWebUI sync URL (current chat front-end; revisit when Hermes/external agents become primary)
- METATRON_OPENWEBUI_METATRON_URL ("") — external Metatron URL for OpenWebUI Direct Connections
- MEMORY_SEARCH_DENSE_WEIGHT (0.6) — blend weight for normalized Qdrant dense score in memory hybrid search
- MEMORY_SEARCH_GRAPH_WEIGHT (0.3) — blend weight for Neo4j graph-presence signal (scaled by importance_score)
- MEMORY_SEARCH_SESSION_WEIGHT (0.1) — blend weight for Redis session-cache presence boost
- MEMORY_SEARCH_TOP_K_MULTIPLIER (3) — per-leg fetch multiplier for dedup/filter headroom
- METATRON_FRESHNESS_ENABLED (false) — master flag for freshness worker (MTRNIX-304 Phase A); when false, producer is a no-op and `python -m metatron.memory.freshness` exits immediately
- METATRON_FRESHNESS_POLL_SECONDS (2.0) — worker poll interval when queue is idle
- METATRON_FRESHNESS_MAX_JOBS_PER_ITERATION (20) — max jobs drained per bounded-loop iteration
- METATRON_FRESHNESS_LOCK_TTL_SECONDS (30) — TTL for per-workspace Lua-scripted Redis locks
- METATRON_FRESHNESS_STALE_AFTER_DAYS (30) — age after which FreshnessMonitor flags records as stale
- METATRON_FRESHNESS_DECISION_CONFIDENCE_THRESHOLD (0.7) — DecisionEngine confidence floor to auto-apply rather than queue for review
- METATRON_FRESHNESS_LLM_MODEL (qwen2.5-4b-instruct-q4) — SLM model for DecisionEngine
- METATRON_FRESHNESS_LLM_PROVIDER ("") — optional provider override; auto-switches to `custom` when `METATRON_FRESHNESS_LLM_API_BASE_URL` is set
- METATRON_FRESHNESS_LLM_API_BASE_URL ("") — custom provider base URL for freshness SLM
- METATRON_FRESHNESS_LLM_API_KEY ("") — API key for freshness SLM provider
- METATRON_FRESHNESS_LINKER_THRESHOLD (0.6) — similarity threshold for Linker stage
- METATRON_FRESHNESS_RECONCILER_THRESHOLD (0.85) — similarity threshold for Reconciler stage
- METATRON_FRESHNESS_BACKOFF_BASE_SECONDS (2.0) — exponential backoff base when worker errors repeat
- METATRON_FRESHNESS_BACKOFF_MAX_SECONDS (60.0) — exponential backoff cap
- METATRON_FRESHNESS_MAX_CONSECUTIVE_ERRORS (10) — consecutive-error count after which worker aborts
- METATRON_FRESHNESS_KB_ENABLED (false) — KB-side freshness producer flag (MTRNIX-313 Phase B); requires `METATRON_FRESHNESS_ENABLED=true`. When off, the KB producer hook in connector sync is a no-op and the worker's KB pipeline is never invoked
- METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED (false) — retrieval-side ARCHIVED/SUPERSEDED filter pushdown; when on, recall channels combine the filter with `access_filter` via `_combine_filters`
- METATRON_FRESHNESS_WEIGHT (0.0) — scoring weight for the `freshness` signal in `compute_signal_score`; default 0.0 keeps the formula numerically identical to Phase A
- METATRON_FRESHNESS_KB_STALE_AFTER_DAYS (90) — KB stale threshold in days (higher than memory's 30 because KB documents age more slowly)
- See core/config.py for full list

## External Agent Integration Surfaces

Metatron exposes three consumer surfaces for external agent runtimes (Hermes, OpenClaw, Cursor,
Claude Desktop, OpenWebUI, LibreChat, custom code). Built-in chat UI / channels are legacy;
new integrations should target these surfaces.

### 1. MCP Server — recommended for agent runtimes
Mounted at `/mcp` (streamable-HTTP). Tools exposed:
- `metatron_search` — hybrid RAG over documents
- `metatron_get` — fetch document by id
- `metatron_store` — index a new document
- `metatron_sync` — trigger connector sync
- `metatron_status` — workspace statistics

Auth: bearer token via `METATRON_MCP_API_KEY`. Memory-specific tools are also exposed:
`memory_store`, `memory_search`, `memory_delete`, `memory_batch_store`, `memory_list`,
`memory_update`. Full reference in `docs/MCP_API.md`.

See `docs/HERMES_INTEGRATION.md` and `docs/OPENCLAW_INTEGRATION.md`.

### 2. OpenAI-Compatible API — for OAI clients
- `GET /v1/models` — list models (one per workspace, format: `metatron-rag-{workspace_id}`)
- `POST /v1/chat/completions` — RAG-backed completions (streaming + non-streaming). Note: this is
  NOT a raw LLM proxy — it runs hybrid_search_and_answer over workspace documents.
- `GET /v1/openapi.json` — connection verification stub

Auth: personal API key (`mtk_...`) per user, or static `METATRON_OPENAI_COMPAT_KEY` fallback.

Memory context injection into system prompt on this endpoint is planned (MTRNIX-275, backlog).
Today agent memory is not automatically added to /v1/chat/completions context.

### 3. Raw REST API
- `/api/v1/memory/*` — agent memory CRUD + hybrid search
- `/api/v1/agents/*` — agent registry CRUD + lifecycle (start/stop/pause) + versioned config
  (WS4, MTRNIX-270). Reads gated by `require_viewer`; writes/lifecycle by `require_editor`.
- `/api/v1/documents`, `/api/v1/search` — document CRUD + search
- `/api/v1/workspaces`, `/api/v1/connections`, `/api/v1/sync` — admin surfaces

### Current chat front-end: OpenWebUI (bundled mode in active use)
OpenWebUI is today's primary chat surface for end users. `METATRON_OPENWEBUI_*` env vars,
`POST /api/v1/admin/import-openwebui-users`, and `auth/openwebui_sync.py` (auto user sync)
all stay supported. Re-evaluate this surface only when external agent runtimes (Hermes,
LibreChat, custom MCP clients) take over as the primary consumer pattern. See `docs/LEGACY.md`
for the broader transition map.

## Testing
- 1150+ tests, `make test` runs unit only
- `asyncio_mode = "auto"` — no pytest.mark.asyncio needed
- Fixtures in tests/conftest.py: settings, sample_document, sample_chunks, sample_user
- Benchmarker tests need optional dep `benchmark-qed`

## Docker
```
docker compose up -d                 # postgres + qdrant + neo4j
docker compose --profile app up      # + API container
docker compose --profile ollama up   # + Ollama
```
Upstream: metatron on port 8000, healthcheck at /health

## Conventions
- Async everywhere: `async def` for handlers, DB calls, LLM calls
- Config via pydantic-settings, env vars with METATRON_ prefix
- Workspace isolation: all queries filtered by workspace_id (JWT claim)
- Graceful degradation: `_safe_call()` — Neo4j down → search works without graph
- Factory pattern: `create_app(settings)` for isolated testing
- Logging: structlog
- Line length: 99 (ruff)
- Type checking: mypy strict mode
- Ruff rules: E, F, I, N, W, UP, B, SIM, TCH

## Migrations
Alembic in `migrations/`. Run `make migrate` after pulling. Create new: `make migrate-new name="description"`.

## Do NOT
- Import from upper layers into lower (especially into core/)
- Break backward compatibility — no plugins = core works as before
- Add dependencies to core/ on anything outside stdlib + pydantic
- Modify interfaces.py protocols without coordinating with enterprise repo
- Delete or rename event constants without checking enterprise subscribers
- Build new features in `channels/`, `finops`, `api/routes/chat.py` — these are legacy, see `docs/LEGACY.md`
- Extend `skills/` engine without first checking whether MCP tool descriptions cover the need (skills/ is currently inactive but reserved)
- Add a built-in agent chat UI / in-memory session store — user-facing chat is the job of external runtimes (Hermes, OpenWebUI, LibreChat). Any new `/api/v1/chat/*` endpoint or in-memory session store is a red flag. (OpenWebUI bundled mode is supported as a packaged chat front-end — that is a separate concern from us building our own chat backend.)
- Couple new work to current 3-role RBAC (viewer/editor/admin) — 5-role model (Viewer/Editor/Agent Admin/Company Admin/Super Admin) is the target; discuss before extending
- Assume "workspace == KB tenant" forever — the agent-era model separates company from agent; `agent_id` is becoming a first-class field in memory records

## Agent Teams

This project uses Claude Code Agent Teams for automated task execution.
Team lead orchestrates teammates through the full lifecycle: Jira → branch → implementation → tests → PR → review → human approval → docs → merge → Jira Done.

### Project Context

- The metatron-arch-guard skill (~/.claude-home/skills/metatron-arch-guard/) contains
  product vision and architectural constraints. Architect must read it before planning.
  If product vision is outdated, lead should provide corrections in the spawn prompt.
- `.claude/CLAUDE.md` files are scattered across subdirectories (e.g. `src/metatron/retrieval/.claude/`,
  `src/metatron/storage/.claude/`). These contain module-specific rules and context.
  Architect must scan for them: `find . -path '*/.claude/CLAUDE.md' -not -path './node_modules/*'`
  and read those relevant to the affected layers.
- `docs/superpowers/` contains specs, implementation plans, and notes from previous tasks.
  This is the primary source of context about what has already been done, what is planned,
  and what remains to be finished. Architect must read relevant files before planning.
- All required services (PostgreSQL, Qdrant, Neo4j) are assumed to be already running.
  Tests and eval access them directly, no API server needed.

### Teammate Roles

**architect** — Planning & decomposition
- Reads the Jira task (via mcp-atlassian) and its parent story/epic for broader context
- Reads docs/superpowers/ for existing specs, plans, and notes from previous tasks
- Reads metatron-arch-guard skill for product vision and architectural constraints
- Scans and reads relevant `.claude/CLAUDE.md` files in affected subdirectories
- Analyzes which layers (L0–L6) and files are affected
- Checks architectural constraints: no upward imports, core/ has zero external deps
- Produces an implementation plan with ordered subtasks
- Decides if task needs new migration, config vars, event constants, or interface changes
- Validates that plan doesn't break plugin backward compatibility
- Hands off plan to coder with explicit file list and acceptance criteria

Instructions for architect:
```
You are the architect for Metatron Core (MTRNIX).
Before writing any code, you MUST:
1. Fetch the Jira task details using mcp-atlassian
2. Check if the task has a parent story or epic — fetch it for broader context
3. Read docs/superpowers/ — specs, plans, and notes from previous tasks.
   Understand what was already implemented and what is planned.
4. Read CLAUDE.md in the project root for architecture rules and conventions
5. Read the skill at ~/.claude-home/skills/metatron-arch-guard/ for product vision
   and architectural constraints (repo boundaries, DB layer separation, workspace isolation)
6. Scan for module-specific context:
   find . -path '*/.claude/CLAUDE.md' -not -path './node_modules/*'
   Read those relevant to the layers you identified as affected.
7. Identify affected layers (L0-L6) — enforce strict one-way dependencies
8. Check if changes touch interfaces.py or event constants — flag for coordination
9. Produce a plan: affected files, new files, migrations needed, config vars
10. Verify the plan respects: async everywhere, workspace isolation, graceful degradation
Do NOT write implementation code. Output only the plan with acceptance criteria.
```

**coder** — Implementation & tests
- Receives the plan from architect
- Implements changes following project conventions (async, pydantic-settings, structlog, ruff rules)
- Writes/updates unit tests for all new code
- Runs `make lint`, `make typecheck`, `make test` after implementation
- If tests fail — fixes and reruns until green
- Commits with conventional format: `feat(MTRNIX-XXX): description` or `fix(MTRNIX-XXX): description`

Instructions for coder:
```
You are the coder for Metatron Core.
You receive an implementation plan from the architect. Follow it precisely.
Rules:
- async def for all handlers, DB calls, LLM calls
- Config via env vars with METATRON_ prefix, add to core/config.py Settings
- All queries must filter by workspace_id
- Use _safe_call() pattern for optional services (graph, reranker)
- Line length: 99. Ruff rules: E, F, I, N, W, UP, B, SIM, TCH
- Type hints everywhere, mypy strict
- Write unit tests in tests/unit/, use existing fixtures from conftest.py
- asyncio_mode = "auto" — no pytest.mark.asyncio needed
After implementation:
1. Run: make lint && make typecheck && make test
2. Fix any failures, rerun until green
3. Commit: git add -A && git commit -m "feat(MTRNIX-XXX): description"
4. Push: git push -u origin feature/MTRNIX-XXX
```

**reviewer** — Code review & quality gate
- Runs AFTER coder finishes and pushes
- Reviews the full diff against architectural rules
- Checks: layer violations, missing tests, missing type hints, broken conventions
- Checks: backward compatibility (no plugins = core works as before)
- Checks: no imports from upper layers into lower, no new deps in core/
- Runs `make test-all` (including integration) and `make eval` if search-related
- Reports issues back to coder with specific file:line references
- Approves only when all checks pass

Instructions for reviewer:
```
You are a senior reviewer for Metatron Core.
Review the current branch diff against the develop branch.
Check for:
1. Layer violations — no upward imports (e.g., storage/ must not import from services/)
2. Missing async — all IO must be async
3. Missing workspace_id filtering — data leak risk
4. Backward compatibility — core must work without plugins installed
5. Missing tests — every new function needs a unit test
6. Type safety — no Any types without justification, mypy strict
7. Convention violations — naming (snake_case), line length (99), ruff rules
8. Event/interface changes — must be coordinated with enterprise repo
9. Security — no secrets in code, no hardcoded credentials
Run: make test-all
If search pipeline is affected, also run: make eval-compare
Report each issue as: [SEVERITY] file:line — description
Severity: BLOCKER (must fix), WARNING (should fix), SUGGESTION (nice to have)
Only approve when zero BLOCKERs remain.
```

**documenter** — Documentation updates
- Runs AFTER human approval (see pipeline below)
- Updates CLAUDE.md if architecture, commands, config, or conventions changed
- Updates relevant `.claude/CLAUDE.md` files in affected subdirectories
- Updates README.md if user-facing behavior changed
- Updates CHANGELOG.md with the change description
- If new env vars added — documents them in CLAUDE.md Key Config section
- If new API endpoints — documents in relevant section
- Commits docs separately: `docs(MTRNIX-XXX): update documentation`

Instructions for documenter:
```
You are the documenter for Metatron Core.
After human approval is received, update all relevant documentation:
1. CLAUDE.md (root) — if any of these changed: architecture, commands, config vars,
   conventions, source layout, search pipeline, databases, plugin system, auth flow
2. .claude/CLAUDE.md files in affected subdirectories — if module-specific rules changed
3. README.md — if user-facing behavior, setup steps, or API endpoints changed
4. CHANGELOG.md — add entry under [Unreleased]: "- feat/fix: description (MTRNIX-XXX)"
Rules:
- Keep CLAUDE.md format consistent with existing sections
- New env vars go into "Key Config" section with default value and description
- New commands go into "Quick Commands" section
- Do NOT remove or reorder existing documentation without explicit instruction
Commit: git add -A && git commit -m "docs(MTRNIX-XXX): update documentation"
Push: git push
```

### Full Pipeline Prompt

To run the complete Jira-to-merge flow, use this prompt with the team lead:

```
Take task MTRNIX-XXX from Jira.
Create agent team with 4 teammates: architect, coder, reviewer, documenter.

Flow:
1. Update develop and create branch:
   git checkout develop && git pull && git checkout -b feature/MTRNIX-XXX
2. architect: fetch task from Jira (including parent story/epic),
   read docs/superpowers/ for context from previous tasks,
   read metatron-arch-guard skill for product vision,
   scan .claude/CLAUDE.md files in affected directories,
   analyze affected layers, create implementation plan
3. coder: implement plan, write tests, run lint/typecheck/test, commit and push
4. Create PR to develop: gh pr create --base develop --title "feat(MTRNIX-XXX): short description"
5. reviewer: review diff, run make test-all, if BLOCKERs found — send back to coder
   for fixes. Loop until zero BLOCKERs.
6. ⏸️ PAUSE — show summary: what was done, changed files, test results.
   Wait for human confirmation before proceeding.
7. After human "ok": documenter updates documentation (CLAUDE.md, README, CHANGELOG,
   affected .claude/CLAUDE.md files), commits, pushes
8. When all checks pass — merge PR: gh pr merge --squash
9. Transition task MTRNIX-XXX to Done in Jira

Quality: high code standards, all tests green, zero BLOCKERs from reviewer.
```

### Team Composition Notes

- Start with this 4-teammate setup. If tasks are small (bug fixes, config changes),
  skip architect — let coder work directly from Jira description.
- For search pipeline tasks, reviewer must additionally run `make eval-compare`.
- For tasks touching interfaces.py or event constants, architect must flag
  coordination needed with enterprise repo before coder starts.
- Each teammate loads root CLAUDE.md automatically but does NOT inherit lead's
  conversation history. Task-specific context must be included in the spawn prompt.
- The human approval pause (step 6) is mandatory. Do not skip it.
  Lead must present: changed files summary, test results, reviewer verdict.
- All services (PostgreSQL, Qdrant, Neo4j) are assumed running.
  If a test fails due to connection errors, notify the human — do not attempt
  to start services autonomously.