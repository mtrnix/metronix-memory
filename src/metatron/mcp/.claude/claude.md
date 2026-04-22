# MCP

## Overview
L3 — Model Context Protocol server and client. Exposes Metatron's knowledge base
as MCP tools for Claude and other MCP-compatible clients. Dual transport: stdio
(local dev) and streamable-http (production, mounted at `/mcp`).

## Files

### `server.py`
`FastMCP` server instance (`mcp`) — module-level singleton imported by `api/app.py`.

Transport modes:
- `TRANSPORT_STDIO` — for local MCP clients, subprocess invocation
- `TRANSPORT_HTTP` (streamable-http) — mounted at `/mcp` in FastAPI app

`get_server() -> FastMCP` — returns the singleton `mcp` instance.
`run_stdio()` / `run_http(host, port)` — transport-specific runners.
`main(transport)` — CLI entry point (`__main__.py`).

**Mount in FastAPI:** `api/app.py` calls `mcp_server.streamable_http_app()` and appends
a `StarletteRoute("/mcp", ...)` directly (not `Mount` — avoids 405 on POST without trailing slash).
Session manager initialized in lifespan: `async with mcp_server.session_manager.run()`.

### `tools/__init__.py`
Imports all tool modules — registering them with the FastMCP server via `@mcp.tool()` decorators.
Imported as `import metatron.mcp.tools` in `api/app.py` (side-effect import).

### `tools/search.py`
`metatron_search(query, workspace_id, top_k)` — `@mcp.tool()`
Calls `hybrid_search_and_answer()` via `asyncio.to_thread()`.
Returns answer + source fragments. Slow (20–60s) — full RAG with LLM synthesis.

### `tools/search_fast.py`
`metatron_search_fast(query, workspace_id, top_k)` — `@mcp.tool()`
Low-latency vector search (P50 < 800ms). No reranker, HyDE, graph enrichment, or LLM stage.
Returns raw document chunks. Default search tool for interactive agent use.

### `tools/get.py`
`metatron_get(document_id, workspace_id)` — `@mcp.tool()`
Fetches a specific document by ID from Qdrant/PostgreSQL.

### `tools/store.py`
`metatron_store(content, title, workspace_id, metadata)` — `@mcp.tool()`
Indexes a new document directly (bypasses connector pipeline).

### `tools/sync.py`
`metatron_sync(connection_id, workspace_id)` — `@mcp.tool()`
Triggers a connector sync for the given connection.

### `tools/status.py`
`metatron_status(workspace_id)` — `@mcp.tool()`
Returns workspace stats: document count, chunk count, last sync time.

### `tools/memory_store.py`
`memory_store(content, agent_id, workspace_id, scope, tags, importance_score, source_type, session_id)` — `@mcp.tool()`
Persists an agent memory record across PG (source of truth) + Qdrant + Neo4j.
Content-hash dedup. `scope` = `global | per_agent | session`. Delegates to `MemoryService.save()`.

### `tools/memory_search.py`
`memory_search(query, agent_id, workspace_id, scope?, tags?, session_id?, top_k)` — `@mcp.tool()`
Hybrid search over agent memory. Blends Qdrant dense + Neo4j graph presence + Redis session boost.
Delegates to `MemorySearchService.hybrid_search()`.

### `tools/memory_delete.py`
`memory_delete(record_id, workspace_id)` — `@mcp.tool()`
Removes a persistent memory record from PG + Qdrant + Neo4j. Session-scoped records
are managed via session lifecycle, not this tool.

### `tools/memory_batch_store.py`
`memory_batch_store(records, agent_id, workspace_id, scope, importance_score, source_type, session_id)` — `@mcp.tool()`
Persists up to 100 records sequentially with per-record dedup. Individual failures do not
abort the batch (`error` field on failed entries). Added in MTRNIX-310.

### `tools/memory_list.py`
`memory_list(agent_id, workspace_id, scope?, tags?, limit, offset)` — `@mcp.tool()`
Paginated enumeration of memory records. Delegates to `MemoryPostgresStore.list_records()`
+ `count_records()`. Tags filter is a post-filter (tags JSONB array filter not pushed to PG).

### `tools/memory_update.py`
`memory_update(record_id, workspace_id, content?, tags?, importance_score?)` — `@mcp.tool()`
Partial in-place update. Neo4j relationships preserved. If `content` changes — Qdrant re-embed;
if only `tags`/`importance_score` — `update_payload()` only, no re-embedding.

### `tools/_memory_deps.py`
`build_memory_service_for_workspace(workspace_id)` — dependency factory used by all memory tools
to construct a workspace-scoped `MemoryService` with its four backends.

### `tools/_memory_utils.py`
Shared helpers for memory tools: scope parsing, DTO conversion, error formatting.

### `tools/models.py`
Pydantic models for MCP tool inputs/outputs (used for JSON schema generation).
Includes `MemoryRecordDTO`, `MemoryBatchStoreResponse`, `MemoryListResponse`,
`MemoryUpdateResponse`.

### `client.py`
`MCPClient` — async client for calling external MCP servers.
`connect(config: MCPServerConfig)`, `call_tool(name, params) -> dict`, `list_tools() -> list`.
Used by `agent/executor.py` to call third-party MCP servers configured by enterprise.

### `adapter.py`
`GenericMCPAdapter` — bridges external MCP server tools into Metatron's ingestion pipeline.

`classify_tool(name, description) -> str` — heuristic: "list"/"search" vs "read"/"get".
`select_read_tools(tools) -> list` — filters to document-retrieval tools.
`_find_tool_by_names(tools, candidates)` — fuzzy tool name matching.

`GenericMCPAdapter.index_all(workspace_id)` — discovers MCP tools, calls list/read tools,
converts results to `Document` objects, passes to ingestion pipeline.

`register_adapter(pattern, cls)` / `get_adapter(config) -> GenericMCPAdapter`
— registry for custom adapter implementations per MCP server pattern.

### `action_planner.py` / `action_executor.py` / `action_store.py` — legacy-adjacent
Used only by `agent/router.py._handle_action()` → the in-app agent router that powers
legacy `channels/` and `api/routes/chat.py`. External agent runtimes (Hermes, OpenClaw,
Cursor, Claude Desktop) call MCP tools directly and do NOT go through this flow.

- `ActionPolicy` — allowed/denied action patterns per workspace.
- `ActionPlanner` — LLM-based natural-language → tool call plan.
- `ActionExecutor` — executes plans with timeout/retry/rollback.
- `get_action_store()` — PostgreSQL `config` table, JSONB-backed pending actions.

Do NOT extend for new functionality. Scheduled to follow `channels/` into the legacy
extraction plan (see `docs/LEGACY.md`).

### `registry.py`
`MCPServerRegistry` — manages configured external MCP server connections.
`register(config: MCPServerConfig)`, `get(name) -> MCPServerConfig`, `list() -> list`.

### `auth.py`
MCP-specific auth helpers. Token extraction and validation for MCP transport.

### `config.py`
`MCPServerConfig` dataclass — `name`, `url`, `transport`, `api_key`, `tools_filter`.

### `errors.py`
MCP-specific exception types: `MCPConnectionError`, `MCPToolNotFoundError`, `MCPTimeoutError`.

### `pagination.py`
`MCPPaginator` — cursor-based pagination for MCP list tool responses.

### `sync.py`
`MCPSyncJob` — background job that periodically calls `GenericMCPAdapter.index_all()`
to keep MCP-sourced documents up to date.

## Key Patterns
- **Side-effect tool registration** — `import metatron.mcp.tools` in `api/app.py` registers all `@mcp.tool()` handlers as a side effect
- **Session manager in lifespan** — `mcp_server.session_manager.run()` must be active for HTTP transport to work
- **stdio stdout discipline** — server.py sets `logging` to WARNING level because stdout is reserved for JSON-RPC messages
- **Generic adapter** — `GenericMCPAdapter` can index any MCP server without custom code, using tool name heuristics

## Dependencies
- **Depends on**: `core.models`, `core.config`, `retrieval.search` (metatron_search tool), `ingestion.pipeline` (metatron_store tool), `storage.postgres` (action_store)
- **Depended on by**: `api.app` (mounted at /mcp), `agent.executor` (calls external MCP via client.py)
