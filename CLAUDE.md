# CLAUDE.md — Metatron Core

## What is this
Metatron Core (MTRNIX) — open-source self-hosted RAG system for corporate knowledge management. Python 3.12+, FastAPI + asyncio.

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
make graph-rebuild    # rebuild Neo4j graph from Qdrant data (after graph loss)
make graph-rebuild-dry # preview what graph-rebuild would process
```

Direct commands:
```
python -m metatron          # API + all bots (Telegram/Discord/Slack)
python -m metatron.api.app  # API only
pytest tests/unit/test_search.py::test_name -v  # single test
```

## Architecture (6 layers — strict one-way dependencies, never import upward)
```
L6  api/            REST API (FastAPI routes, middleware, dependencies)
L5  channels/       Telegram, Discord, Slack bots
L4  agent/          Intent router, sessions, commands, executor
L3  services        connectors/, llm/, mcp/, skills/, auth/, workspaces/
L2  processing      ingestion/, retrieval/, benchmarker/
L1  storage/        PostgreSQL, Qdrant, Neo4j clients (no business logic)
L0  core/           Config, Interfaces, Models, Events, Plugin (ZERO upward deps)
```

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
│   └── user_mapping.py        # TODO: NotImplementedError
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
├── agent/                     # L4 — router.py, sessions.py, commands.py, executor.py, tools.py
├── channels/                  # L5 — telegram.py, discord.py, slack.py
├── connectors/                # L3 — confluence, jira, notion, github, gdrive, slack_history, files
│   └── registry.py            # Connector registry (independent from PluginManager)
├── ingestion/                 # L2 — pipeline.py, chunking.py, dedup.py, bm25.py, sync.py
│   └── processors/            # pdf, html, office, text, tabular, dates, titles, translation
├── llm/                       # L3 — provider.py, embeddings.py, base.py
│   └── providers/             # ollama, deepseek, openrouter, custom
├── mcp/                       # L3 — server.py, client.py, adapter.py, registry.py
│   └── tools/                 # search, sync, get, store, status
├── retrieval/                 # L2 — search.py, channels.py, scoring.py, query_classifier.py,
│                              #   hybrid.py, query_expansion.py, reranker.py, token_budget.py
├── storage/                   # L1 — postgres.py, qdrant.py, neo4j_graph.py, encryption.py
├── observability/             # health.py, metrics.py, tracer.py
├── workspaces/                # L3 — manager.py, models.py, persistence.py
├── skills/                    # L3 — engine.py
├── benchmarker/               # L2 — api/, db/, schemas/, services/metrics/
└── scripts/                   # graph_audit.py, run_eval.py, grid_search_weights.py
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
→ require_admin() / require_editor() check role level
```

## Search Pipeline
```
Query → expansion → classify(profile) → weight_preset
     → recall_dense + recall_exact + recall_metadata + recall_graph  (parallel via ThreadPoolExecutor)
     → merge_channels → compute_signal_score(6 weighted signals, normalized [0,1])
     → top-35 pool → cross-encoder rerank (bge-reranker-v2-m3)
     → compute_final_score(blend: 30% signal + 70% reranker)
     → _prepend_root_context (fetch root chunks for child results, prepend as context)
     → _collect_frags(dict) → _mark_evidence_role(PRIMARY/SUPPORTING)
     → _build_ctx(grouped markdown) → LLM(evidence rules) → _append_sources → answer

Scoring signals: dense, graph, metadata, recency, source_balance (smooth gradient).
Weights configurable per query profile (execution, documentation, user_file, relationship, temporal, mixed).
Grid search script: `make grid-search` for weight optimization.

Source citation format: `"{icon} {title} — {url}"` (em-dash separator).
Icons: 📄 confluence, 📋 jira, 📎 upload, 📓 notion.
Frontend splits on `" — "` to extract URL; no URL → title only.
```

## Databases
- **PostgreSQL 16** — metadata, users, BM25 index, logs (port 5432)
- **Qdrant v1.16** — vector embeddings 768-dim (port 6333/6334)
- **Neo4j CE v5** — knowledge graph Document→Chunk→Entity (port 7687 bolt, 7474 browser)
- **Ollama** (optional) — local LLM + embeddings (port 11434)

## Key Config (env vars, prefix METATRON_)
- AUTH_ENABLED (false) — JWT gate on /api/v1/*
- LLM_PROVIDER (ollama) — ollama|deepseek|openrouter|custom
- RERANKER_ENABLED (true) — bge-reranker-v2-m3
- QUERY_EXPANSION_ENABLED (true) — LLM query expansion
- GRAPH_EXTRACTION_ENABLED (true) — NER → Neo4j
- GRAPH_EXTRACTION_WORKERS (1) — parallel workers for graph extraction
- QUERY_CLASSIFIER_ENABLED (true) — hybrid rule+LLM query classifier
- HIERARCHICAL_CHUNKING_ENABLED (true) — root-child chunking in ingestion pipeline
- DENSE_WEIGHT (0.35), GRAPH_WEIGHT (0.15), METADATA_WEIGHT (0.20), RECENCY_WEIGHT (0.10), BALANCE_WEIGHT (0.05), BLEND_WEIGHT (0.3) — scoring formula weights
- RERANK_POOL_SIZE (35) — candidates sent to cross-encoder
- MIN_SIGNAL_SCORE (0.0) — confidence threshold (0=disabled)
- METATRON_OPENAI_COMPAT_ENABLED (true) — OpenAI-compatible API for Open WebUI
- METATRON_OPENAI_COMPAT_KEY ("") — static API key for OpenAI-compat endpoints (Home scenario)
- METATRON_OPENWEBUI_URL ("") — Open WebUI URL for bundled user sync
- METATRON_OPENWEBUI_METATRON_URL ("") — external Metatron URL written into Direct Connections
- See core/config.py for full list

## Open WebUI Integration
Metatron exposes OpenAI-compatible API at `/v1/` for use with Open WebUI or any OpenAI-compatible client.

Endpoints:
- `GET /v1/models` — list models (one per workspace, format: `metatron-rag-{workspace_id}`)
- `POST /v1/chat/completions` — chat completions (streaming + non-streaming)
- `GET /v1/openapi.json` — stub for connection verification

Auth: personal API key (`mtk_...`) per user, or static `METATRON_OPENAI_COMPAT_KEY` fallback (Home scenario).

Three deployment scenarios:
1. **Home** — single user, no auth, static API key via global Open WebUI connection
2. **Bundled** — multi-user, Metatron syncs users to Open WebUI, each gets personal API key + Direct Connection
3. **External** — import users from existing Open WebUI via `POST /api/v1/admin/import-openwebui-users`

In Bundled/External, `ENABLE_DIRECT_CONNECTIONS=true` is mandatory in Open WebUI. Without it users share a global API key and can spoof each other's identity.

Bundled sync: on startup Metatron auto-registers `admin@metatron.local` in Open WebUI. On user CRUD, changes are mirrored. OWUI admin password is the same as `AUTH_PASSWORD` (default: `metatron`).

Docker: Open WebUI available in `docker-compose.full.yml` with profile `openwebui` on port 3080.

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
Возьми задачу MTRNIX-XXX из Jira.
Создай agent team из 4 teammates: architect, coder, reviewer, documenter.

Flow:
1. Обнови develop и создай ветку:
   git checkout develop && git pull && git checkout -b feature/MTRNIX-XXX
2. architect: получи задачу из Jira (включая parent story/epic),
   прочитай docs/superpowers/ для контекста предыдущих задач,
   прочитай metatron-arch-guard skill для product vision,
   просканируй .claude/CLAUDE.md файлы в затронутых директориях,
   проанализируй затронутые слои, создай план реализации
3. coder: реализуй план, напиши тесты, прогони lint/typecheck/test, закоммить и запушь
4. Создай PR в develop: gh pr create --base develop --title "feat(MTRNIX-XXX): краткое описание"
5. reviewer: проверь diff, прогони make test-all, если есть BLOCKERs — верни coder
   на исправление. Цикл пока zero BLOCKERs.
6. ⏸️ ПАУЗА — покажи мне summary: что сделано, какие файлы изменены, результаты тестов.
   Жди моего подтверждения перед продолжением.
7. После моего "ок": documenter обновляет документацию (CLAUDE.md, README, CHANGELOG,
   затронутые .claude/CLAUDE.md), коммитит, пушит
8. Когда все проверки пройдены — замержь PR: gh pr merge --squash
9. Переведи задачу MTRNIX-XXX в статус Done в Jira

Качество: высокий стандарт кода, все тесты зелёные, zero BLOCKERs от reviewer.
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