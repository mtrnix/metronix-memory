# Core

## Overview
L0 — foundation layer. Zero dependencies on anything above it (only stdlib + pydantic).
Defines all contracts: config, data models, ABCs, plugin system, event bus, exceptions.
Every other layer imports from core; core never imports upward.

## Files

### `config.py`
`Settings` (pydantic-settings) — single source of truth for all env vars.
All env vars use `METATRON_` prefix (or explicit aliases like `POSTGRES_HOST`).
Key groups: Application, Auth, PostgreSQL, Qdrant, Memgraph, Ollama, LLM providers,
Search tuning, Graph extraction, Embedding cache, Retrieval weights.

Computed properties: `postgres_dsn` (asyncpg), `postgres_sync_dsn` (psycopg2),
`memgraph_uri` (bolt://), `ollama_llm_url` (handles full URL or host:port).

`get_settings()` — module-level cached singleton, created once from env.

Key search-tuning constants:
- `dense_weight=0.35`, `sparse_weight=0.20`, `tag_weight=0.20`, `graph_weight=0.15`, `recency_weight=0.10`
- `rrf_k=60`, `embedding_dim=768`
- `search_pool_multiplier=3`, `search_pool_min=15`

### `models.py`
Pure dataclasses — no ORM, no Pydantic, no business logic. These shapes flow between all layers.

- `Document` — fetched from connector before chunking (id, workspace_id, source_type, source_id, title, content, url, tags, metadata)
- `Chunk` — post-chunking unit for embedding (chunk_type: ROOT/CHILD/STANDALONE, parent_id, content, token_count, simhash, embedding)
- `DocumentVersion` — temporal tracking with content_hash and changed_fields
- `IncomingMessage` / `OutgoingMessage` — channel messaging shapes
- `Skill` — Markdown document teaching LLM tool usage (name, content, triggers, builtin flag)
- `Connection` — data-source connection with Fernet-encrypted config
- `FileRecord` — uploaded file metadata with sha256
- `User` — internal user with Role and workspace_ids
- `Workspace` — isolated tenant (id, name, slug)
- `SyncResult` — connector sync outcome with counts and errors
- `QueryStep` — single step in 7-step query trace for benchmarker

Enums: `ChunkType` (ROOT, CHILD, STANDALONE), `Role` (VIEWER, EDITOR, ADMIN), `ConnectionStatus` (ACTIVE, SYNCING, ERROR, DISABLED)

### `interfaces.py`
8 ABCs + 2 Protocols — the extension contracts for enterprise.

ABCs:
- `ConnectorInterface` — `configure(connection, decrypted_config)`, `fetch(workspace_id, since)`, `health_check()`
- `ChannelInterface` — `start()`, `stop()`, `send(OutgoingMessage)`
- `LLMProviderInterface` — `chat(messages, tools, temperature)`, `embed(texts)`
- `VectorStoreInterface` — `ensure_collection()`, `upsert()`, `search_dense()`, `search_sparse()`
- `GraphStoreInterface` — `add_entities()`, `add_relations()`, `query_neighbors()`
- `ProcessorInterface` — `supported_types()`, `extract_text(content, filename)`
- `AuthBackendInterface` — `authenticate(token) -> User | None`, `create_token(user)`
- `RetrieverInterface` — `retrieve(workspace_id, query, top_k)`

Protocols (`@runtime_checkable`):
- `EventHandler` — `async __call__(event_name, payload)` — for event bus subscribers
- `PipelineHook` — `async __call__(context) -> context` — chainable pipeline interceptor

### `events.py`
`EventBus` — async pub/sub in-process event bus.
- `subscribe(event_name, handler)` — register async handler
- `emit(event_name, payload)` — call all handlers; failing handler is logged and skipped
- `clear(event_name)` — remove handlers (used in tests)

Constants: `DOCUMENT_INDEXED`, `CHUNK_CREATED`, `QUERY_EXECUTED`, `USER_AUTHENTICATED`,
`SYNC_STARTED`, `SYNC_COMPLETED`, `SYNC_FAILED`

### `plugin.py`
`PluginManager` — central registry for enterprise extensions.
Stored in `app.state.plugin_manager`, created once in `create_app()`.

Registration API (called by plugins):
- `register_auth_provider(AuthBackendInterface)` — replaces JWT auth (only one active; second call warns)
- `register_middleware(cls, **kwargs)` — adds Starlette middleware
- `register_event_handler(event_name, handler)` — subscribes to EventBus
- `register_routes(router, prefix)` — adds APIRouter
- `register_pipeline_hook(hook_name, PipelineHook)` — stage names: `pre_search`, `post_search`, `pre_chunk`, `post_chunk`, `pre_index`, `post_index`
- `register_sso_provider(provider)` — SSO provider (enterprise auth)

`apply_to_app(app)` — wires all registered extensions into FastAPI.

`discover_plugins(manager)` — scans `"metatron.plugins"` entry point group.
Fault-tolerant: failing plugin is logged and skipped. Core always starts.

`MetatronPlugin` protocol — every plugin class must implement `name`, `version`, `register(manager)`.

### `exceptions.py`
Typed hierarchy — all layers raise only these. No bare `Exception`.

```
MetatronError
├── ConnectorError
│   └── RateLimitError  (retry_after: float = 60.0)
├── AuthenticationError
├── IntegrityError
├── SecurityError
├── ToolDisabledError
└── ToolTimeoutError
```

### `logging.py`
`configure_logging(log_level, json_output)` — sets up structlog.
JSON output in staging/production, colored console in development.
`bind_context(**kwargs)` — adds key-value pairs to current log context.

### `http.py`
`get_http_session()` — singleton `requests.Session` with retry logic.
Used by connectors and LLM providers for synchronous HTTP calls.

### `utils.py`
- `normalize_text(text)` — whitespace normalization
- `normalize_workspace_id(workspace_id)` — slug normalization
- `build_doc_label(source_type, source_id)` — `"{source_type}:{source_id}"`

## Key Patterns
- **Zero upward deps**: core never imports from agent/, api/, storage/, etc.
- **Dataclass shapes**: models are pure dataclasses — no ORM contamination
- **Single cached settings**: always use `get_settings()`, never instantiate `Settings()` directly outside tests
- **Plugin-first**: enterprise swaps implementations without touching core code
- **Fault-tolerant bus**: `EventBus.emit()` never raises — bad handlers are logged and skipped

## Dependencies
- **Depends on**: stdlib, pydantic, pydantic-settings, structlog only
- **Depended on by**: all other layers (api, auth, agent, channels, connectors, ingestion, llm, mcp, retrieval, storage, workspaces, skills, observability)
