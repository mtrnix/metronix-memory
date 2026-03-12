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
make docker-up        # start postgres + qdrant + memgraph
make docker-down
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
L1  storage/        PostgreSQL, Qdrant, Memgraph clients (no business logic)
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
│                              # workspaces, sync, benchmarker, dashboard/, files, graph, health
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
├── retrieval/                 # L2 — search.py, hybrid.py, query_expansion.py, scoring.py,
│                              #   reranker.py, entity_resolver.py, token_budget.py
├── storage/                   # L1 — postgres.py, qdrant.py, memgraph.py, encryption.py
├── observability/             # health.py, metrics.py, tracer.py
├── workspaces/                # L3 — manager.py, models.py, persistence.py
├── skills/                    # L3 — engine.py
├── benchmarker/               # L2 — api/, db/, schemas/, services/metrics/
└── scripts/                   # graph_audit.py
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
Query → expansion → entity injection → hybrid_search (dense+sparse, pool=75)
→ merge + diversify (k=50) → title_boost → RERANKER (bge-reranker-v2-m3, top 25)
→ collect_frags → graph enrichment → token budget → LLM → sources
```

## Databases
- **PostgreSQL 16** — metadata, users, BM25 index, logs (port 5432)
- **Qdrant v1.16** — vector embeddings 768-dim (port 6333/6334)
- **Memgraph v2.18** — knowledge graph Document→Chunk→Entity (port 7687)
- **Ollama** (optional) — local LLM + embeddings (port 11434)

## Key Config (env vars, prefix METATRON_)
- AUTH_ENABLED (false) — JWT gate on /api/v1/*
- LLM_PROVIDER (ollama) — ollama|deepseek|openrouter|custom
- RERANKER_ENABLED (true) — bge-reranker-v2-m3
- QUERY_EXPANSION_ENABLED (true) — LLM query expansion
- GRAPH_EXTRACTION_ENABLED (true) — NER → Memgraph
- See core/config.py for full list

## Testing
- 915+ tests, `make test` runs unit only
- `asyncio_mode = "auto"` — no pytest.mark.asyncio needed
- Fixtures in tests/conftest.py: settings, sample_document, sample_chunks, sample_user
- Benchmarker tests need optional dep `benchmark-qed`

## Docker
```
docker compose up -d                 # postgres + qdrant + memgraph
docker compose --profile app up      # + API container
docker compose --profile ollama up   # + Ollama
```
Upstream: metatron on port 8000, healthcheck at /health

## Conventions
- Async everywhere: `async def` for handlers, DB calls, LLM calls
- Config via pydantic-settings, env vars with METATRON_ prefix
- Workspace isolation: all queries filtered by workspace_id (JWT claim)
- Graceful degradation: `_safe_call()` — Memgraph down → search works without graph
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
