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
