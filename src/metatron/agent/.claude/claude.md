# Agent

## Overview
L4 — intent routing, session management, tool execution, and command handling.
Sits between channels (L5) and services (L3). Routes incoming messages from
Telegram/Discord/Slack to the appropriate handler (search, greeting, action, command).

## Files

### `router.py`
`AgentRouter` — sync intent classification and dispatch.

Intent categories (keyword/prefix matching):
- `SEARCH` — default for knowledge queries
- `GREETING` — hello/hi/привет patterns
- `SMALLTALK` — casual conversation
- `ACTION` — tool/connector actions
- `COMMAND` — slash-command prefix (`/`)

`route(message: IncomingMessage) -> OutgoingMessage` — classify + dispatch.
Called via `asyncio.to_thread()` from channel handlers (channels are async, router is sync).

### `sessions.py`
`SessionManager` — thread-safe in-memory conversation history.
Keyed by `(channel, channel_user_id)` pair.
`add_message(session_key, role, content)` — appends to history
`get_history(session_key, max_turns) -> list[dict]` — returns last N turns
`clear(session_key)` — clears history for a session

Follow-up detection: checks if query references previous context ("it", "that", "as before").

### `executor.py`
`ToolExecutor` — async sandboxed tool execution.
HTTP tool calls validated against an allowlist of permitted domains.
Shell tool calls validated against an allowlist of permitted commands.
`execute(tool_name, params, workspace_id) -> dict`

Two-step action confirmation flow:
1. First call returns `{"status": "confirm", "action": ...}`
2. Confirmed call executes and returns result

Uses `asyncio.new_event_loop()` wrappers for MCP/connector calls
that don't run in the main event loop.

### `tools.py`
OpenAI function-calling schemas for agent tools.
Defines JSON schemas passed to LLM for structured tool invocation:
- `search_knowledge_base` — query retrieval
- `sync_connector` — trigger connector sync
- `get_document` — fetch specific document

### `memory_service.py`
`MemoryService` — orchestrates agent memory across stores (WS1).
Bound to a single `workspace_id` at construction. Composes L1 storage:
`MemoryPostgresStore` (source of truth) + `MemoryQdrantStore` + `RedisSessionCache` + `memory_graph.py`.
All public methods assert `workspace_id` matches the bound value.

Session methods (Redis + Neo4j write-through):
- `cache_session(ws, session_id, record, ttl?) -> MemoryRecord` — Redis primary, Neo4j best-effort
- `get_session(ws, session_id, record_id) -> MemoryRecord | None` — Redis first, PG fallback
- `list_session(ws, session_id) -> list[MemoryRecord]`
- `invalidate_session(ws, session_id) -> int`
- `extend_session_ttl(ws, session_id, ttl) -> bool`

Persistent methods (PG + Qdrant + Neo4j):
- `save(ws, record) -> MemoryRecord` — content dedup via exact-match hash, then PG → Qdrant → Neo4j (best-effort). Non-atomic.
- `get(ws, record_id) -> MemoryRecord | None` — PG (source of truth)
- `delete(ws, record_id) -> bool` — PG → Qdrant → Neo4j (best-effort)
- `list_records(ws, agent_id?, scope?, limit?, offset?) -> list[MemoryRecord]` — PG with filters
- `reset(ws, agent_id?, scope?) -> int` — DELETE RETURNING id from PG + per-id Qdrant + Neo4j cleanup
- `promote(ws, session_id, record_id, target_scope?) -> MemoryRecord` — Redis/PG → save to all stores; dedup-aware scope upgrade
- `search(ws, query, agent_id?, scope?, tags?, session_id?, top_k?) -> list[MemorySearchResult]` — delegates to MemorySearchService

### `commands.py`
Legacy stub — slash-command handlers (`/help`, `/sync`, `/clear`).
Not currently used by `AgentRouter` (commands handled inline in router).

## Key Patterns
- **Sync-first** — `AgentRouter.route()` is sync; channels wrap it with `asyncio.to_thread()`
- **`asyncio.new_event_loop()` wrappers** — used when calling async MCP/connector code from sync context
- **Allowlist security** — HTTP and shell tools validated against explicit allowlists before execution
- **Two-step confirmation** — destructive actions (sync, delete) require explicit confirm before execution

## Dependencies
- **Depends on**: `core.models` (IncomingMessage, OutgoingMessage), `retrieval.search` (hybrid_search_and_answer), `mcp.client`, `connectors`
- **Depended on by**: `channels` (telegram.py, discord.py, slack.py)
