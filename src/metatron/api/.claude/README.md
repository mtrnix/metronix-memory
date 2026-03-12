# API

## Overview
L6 — top layer. FastAPI application factory, lifespan management, middleware stack,
and all REST endpoints. Creates the app via `create_app(settings)` factory for
isolated testing. Mounts MCP server at `/mcp`.

## Files

### `app.py`
`create_app(settings) -> FastAPI` — application factory.

**Startup order in `create_app()`:**
1. Plugin discovery — `PluginManager()` + `discover_plugins(manager)`
2. CORS middleware — origins from `Settings.cors_origins_list`
3. Plugin middlewares — wired via `plugin_manager.apply_to_app()`
4. `OptionalAuthMiddleware` — outermost, runs first
5. Core routers included at `/api/v1/...`
6. Plugin routers included after core
7. MCP ASGI handler mounted at `/mcp` (GET, POST, DELETE)

**`lifespan()` startup:**
1. `configure_logging()`
2. Auto-run DB migrations via `asyncio.to_thread(run_migrations_sync, ...)`
3. `mcp_server.session_manager.run()` (async context manager)

**Note:** Store initialization (Postgres, Qdrant, Memgraph, Ollama) is TODOed in
lifespan — currently all `get_postgres/vector/graph/llm` dependencies raise `NotImplementedError`.

`main()` — entry point for `python -m metatron.api.app`, runs uvicorn with `factory=True`.

### `middleware.py`
`OptionalAuthMiddleware(BaseHTTPMiddleware)` — JWT gate.

- Always sets `request.state.user = {}` (downstream never gets AttributeError)
- If `AUTH_ENABLED=False` → passes through
- `PUBLIC_PATHS`: `/health`, `/ready`, `/metrics`, `/metrics/reset`, `/api/v1/auth/login`
- OPTIONS requests always pass through (CORS preflight)
- Validates `Bearer` token via `jwt.verify_token()`, sets `request.state.user` dict on success
- Returns 401 JSON on missing or invalid token

### `dependencies.py`
Shared `Depends()` functions:
- `get_settings(request) -> Settings` — from `app.state.settings`
- `get_postgres(request)` — **NotImplementedError** (TODO: return `app.state.postgres`)
- `get_vector_store(request)` — **NotImplementedError**
- `get_graph_store(request)` — **NotImplementedError**
- `get_llm_provider(request)` — **NotImplementedError**

## Routes

### `routes/health.py`
`GET /health` — liveness: `{"status": "ok"}`
`GET /ready` — readiness: checks Qdrant, Memgraph, Ollama async via `asyncio.to_thread()`

### `routes/auth.py`
`POST /api/v1/auth/login` — shared-password login, returns JWT token.
Password validated against `Settings.auth_password`. Issues token for `"admin"` user with `workspace_ids=["*"]`.

### `routes/chat.py`
`POST /api/v1/chat` — main Q&A endpoint. Calls `hybrid_search_and_answer()` via `asyncio.to_thread()`.
`POST /api/v1/chat/stream` — SSE streaming via `EventSourceResponse`.
`POST /api/v1/upload` — file upload + immediate ingestion into workspace.
In-memory conversation history keyed by `user_id` (thread-safe with `threading.Lock`).

### `routes/admin.py`
`GET /api/v1/admin/cleanup/preview` — show what would be deleted (Qdrant + Memgraph)
`POST /api/v1/admin/cleanup` — delete all data (requires `ALLOW_CLEANUP=true`)
`POST /api/v1/admin/cleanup/{workspace_id}` — delete workspace data

### `routes/connections.py`
Full CRUD for data-source connections + sync trigger.
`GET/POST /api/v1/connections` — list / create
`GET/PUT/DELETE /api/v1/connections/{id}` — read / update / delete
`POST /api/v1/connections/{id}/sync` — trigger background sync via `BackgroundTasks`
Uses module-level `ConnectorRegistry` singleton, Fernet-encrypts connector config.

### `routes/documents.py`
`GET /api/v1/documents/{document_id}/history` — paginated version history.

### `routes/files.py`
`POST /api/v1/files/` — upload file, store on disk, SHA-256, PostgreSQL record
`GET /api/v1/files/` — list files for workspace
`GET /api/v1/files/{id}` — file metadata
`GET /api/v1/files/{id}/verify` — SHA-256 integrity check

### `routes/graph.py`
`GET /api/v1/graph/overview` — all nodes/edges for workspace (max 500 nodes)
`GET /api/v1/graph/expand/{node_id}` — neighborhood expansion for a node
Uses Memgraph directly (neo4j driver). Handles `ServiceUnavailable`/`SessionExpired`.

### `routes/skills.py`
`GET/POST /api/v1/skills` — list / create skills
`GET/PUT/DELETE /api/v1/skills/{id}` — read / update / delete

### `routes/workspaces.py`
`GET/POST /api/v1/workspaces` — list / create workspaces
`GET/PUT/DELETE /api/v1/workspaces/{id}` — read / update / delete
Uses `get_workspace_manager()` singleton.

### `routes/sync.py`
`GET /api/v1/sync/status` — sync status per connection (TODO stub)
`GET /api/v1/sync/logs` — recent sync log entries (TODO stub)

### `routes/benchmarker.py`
`POST /api/v1/query/trace` — run query with 7-step timing trace for benchmarking.

### `routes/finops.py`
`GET /api/v1/finops/time-savings` — time savings metrics.
See `routes/.claude/finops.md` for full documentation.

### `routes/dashboard/__init__.py`
Aggregates 3 sub-routers under `/api/v1/dashboard`.

### `routes/dashboard/overview.py`
`GET /api/v1/dashboard/overview` — workspace stats (doc count, chunk count, etc.)
`GET /api/v1/dashboard/activity` — recent activity timeline
`get_valid_workspace()` — shared dependency for workspace validation.

### `routes/dashboard/sync.py`
`GET /api/v1/dashboard/sync/history` — recent sync history entries with status/duration.

### `routes/dashboard/graph.py`
`GET /api/v1/dashboard/graph/lineage` — raw_documents → chunks → graph_nodes counts
`GET /api/v1/dashboard/graph/orphans` — nodes with no edges

## Key Patterns
- **Factory pattern** — `create_app(settings)` enables isolated test instances
- **Middleware order** — `OptionalAuthMiddleware` is outermost (added last via `add_middleware`), runs first on every request
- **Store dependencies are stubs** — `get_postgres/vector/graph/llm` all raise `NotImplementedError`; routes that need stores import directly (e.g. `from metatron.storage.qdrant import get_hybrid_store`)
- **MCP mount** — uses `StarletteRoute` directly (not `Mount`) to avoid 405 on POST without trailing slash
- **Plugin route isolation** — plugin routes included after all core routes

## Dependencies
- **Depends on**: `core`, `auth`, `storage`, `retrieval`, `connectors`, `workspaces`, `mcp`, `ingestion`, `observability`
- **Depended on by**: nothing (top of the stack)
