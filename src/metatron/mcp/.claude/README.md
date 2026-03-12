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
Returns answer + source fragments.

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

### `tools/models.py`
Pydantic models for MCP tool inputs/outputs (used for JSON schema generation).

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

### `action_planner.py`
`ActionPolicy` — defines allowed/denied action patterns per workspace.
`ActionPlanner` — generates action plans from natural language descriptions.
Uses LLM to decompose complex tasks into `ActionStep` sequences.

### `action_executor.py`
`ActionExecutor` — executes action plans from `ActionPlanner`.
Step execution with timeout, retry, and rollback on failure.
Results collected into `ActionResult` dict.

### `action_store.py`
Persistence for action plans and execution history.
Stores in PostgreSQL `config` table as JSONB.

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
