# Chat

## Overview
L3 — **ASOC pilot only** (MTRNIX-340, epic). Persistent chat orchestration backend for
ASOC's project-view AI assistant. ASOC builds the UI; this module handles the full
request pipeline: retrieval → visibility filter → MCP tools → LLM streaming → persist.

**This module is NOT a general-purpose chat backend.** It serves exactly one integration
pattern: external UI (ASOC) ↔ Metatron (orchestrator backend). The "no in-memory session
store" and "no built-in chat UI" rules from `CLAUDE.md` still apply — all state lives in
PostgreSQL (`chat_threads`, `chat_messages`), never in process memory.

Layer rule: `chat/` is L3. It may import from L0–L2 (core, storage, retrieval, ingestion)
and other L3 services. It NEVER imports from L4–L6 (agent, channels, api).

## Files

### `models.py`
Pure dataclasses (no ORM):
- `ChatThread(thread_id: UUID, workspace_id, user_id, created_at, last_message_at)`
- `ChatMessage(id: UUID, thread_id, role: ChatMessageRole, content, citations_json, tool_calls_json, created_at)`
- `ChatMessageRole(StrEnum)` — `USER`, `ASSISTANT`, `SYSTEM`, `TOOL`

### `persistence.py` (T3, MTRNIX-353)
`ChatPersistence` — async PostgreSQL DAO for threads and messages.

Key methods:
- `get_or_create_thread(workspace_id, user_id) -> ChatThread` — idempotent; UNIQUE (workspace_id, user_id) in DB
- `get_thread(workspace_id, thread_id) -> ChatThread | None` — workspace-scoped 404 protection
- `list_threads(workspace_id, user_id) -> list[ChatThread]`
- `append_message(workspace_id, thread_id, role, content, citations_json?, tool_calls_json?) -> ChatMessage`
- `list_messages(workspace_id, thread_id, limit?, offset?) -> list[ChatMessage]` — oldest-first
- `delete_thread(workspace_id, thread_id) -> bool` — CASCADE deletes messages; False if not found
- `cascade_delete_user(user_id)` — DELETE all threads+messages for a user across all workspaces (GDPR cascade)

All read/write methods verify `workspace_id` scoping — cross-workspace access returns 404/empty.

### `cleanup.py` (T3, MTRNIX-353)
`ChatHistoryCleanupWorker` — retention-based cleanup cron.
- Runs as an `asyncio.create_task` in the app lifespan.
- Sleeps `METATRON_CHAT_HISTORY_CLEANUP_INTERVAL_SECONDS` (default 86400 s = 1 day) between passes.
- Deletes `chat_messages` older than `METATRON_CHAT_HISTORY_RETENTION_DAYS` (default 90 days).
- Removes orphan `chat_threads` with no remaining messages.

### `asoc_orchestrator.py` (T4, MTRNIX-354)
`AsocChatOrchestrator` — stateless, shared across all requests. Owned by `app.state.asoc_chat_orchestrator`.

**15-step pipeline** (see module docstring for full sequence):
1. Derive `workspace_id` from `auth.project_id` (from `AsocAuthContext`): `asoc-{instance}-{project_id}`
2. Check `bootstrap_state` — reject with SSE error if not `READY`
3. Rate-limit via `InMemoryTokenBucket`
4. `get_or_create_thread` (one per user in MVP)
5. `asyncio.timeout(chat_timeout_seconds)` wraps steps 6–15
6. Retrieval: `hybrid_search_and_answer(stop_at="merged")`
7. `AsocVisibilityFilter.filter_chunks(auth.session_id, ...)` — hard-fail on any error
8. `AsocMcpClient.list_available_tools(auth.session_id)` — graceful degradation on error
9. Prompt assembly (`asoc_prompt`)
10. Persist user message
11. LLM availability check
12. Streaming LLM loop with tool-call accumulation (bounded by `chat_max_tool_calls_per_request`)
13. Process tool calls: `cite_source` (built-in) or ASOC MCP tools (via T6)
14. Emit `sources` SSE event
15. Persist assistant message, emit `done`

**Invariants:**
- `done` is always the last event (success, error, or timeout)
- `error` is always followed by exactly one `done`
- No writes happen after a terminal event

`CITE_SOURCE_TOOL` — built-in LLM function schema; citations collected via tool-call accumulation
and emitted as the `sources` SSE event after the stream.

### `asoc_prompt.py` (T4, MTRNIX-354)
Three pure functions (no I/O, easily testable):

- `build_system_prompt(project_name, mcp_tools) -> str` — ASOC-specific system prompt with
  hard rules: cite every factual claim, admit unknowns, read-only mode, no fabrication.
  Injects MCP tool schema section when `mcp_tools` is non-empty.
- `assemble_history(db_messages, external_history, max_turns, max_tokens) -> list[dict]` —
  merges DB history + ASOC-supplied history payload; truncates to `max_turns` / `max_tokens`.
- `assemble_context(filtered_results, max_chars) -> str` — formats filtered MergedResult chunks
  into a context block injected into the user message.

### `asoc_rate_limit.py` (T4, MTRNIX-354)
`InMemoryTokenBucket` — async per-user token bucket rate limiter.

- One bucket per `user_id`; starts full at `rate_per_min` tokens.
- `acquire(user_id) -> bool` — consumes one token; returns `False` when empty.
- Soft cap of 10 000 user IDs; LRU-style eviction drops oldest 25 % when exceeded.
- **Not shared across worker replicas** (in-process only). Acceptable for MVP single-replica.

### `asoc_sse.py` (T4, MTRNIX-354)
Pure SSE event builder functions. Each returns `{"event": str, "data": str}` for
`sse_starlette.EventSourceResponse`.

| Function | Event name | Purpose |
|----------|-----------|---------|
| `sse_status(status)` | `status` | Pipeline phase: `searching/filtering/answering/tool_calling` |
| `sse_chunk(text)` | `chunk` | LLM streaming token `{"text": "..."}` |
| `sse_sources(citations)` | `sources` | Structured citation array |
| `sse_tool_call(tool, status, reason?)` | `tool_call` | MCP lifecycle: `running/done/error` |
| `sse_done(workspace_id, thread_id)` | `done` | Terminal event (always last) |
| `sse_error(code, message)` | `error` | Error event (always followed by `done`) |

## Dependencies
- **Depends on**: `core.config` (Settings), `core.models`, `retrieval.search` (hybrid_search_and_answer),
  `integrations.asoc_visibility` (T5), `integrations.asoc_mcp_client` (T6),
  `llm.asoc_chat_provider` (T4), `workspaces.bootstrap.store` (T2), `workspaces.bootstrap.models` (T2),
  `storage.postgres` (via ChatPersistence)
- **Depended on by**: `api.routes.asoc_chat` (L6) — imports `AsocChatOrchestrator`, `ChatPersistence`,
  `ChatThread`, `ChatMessage`

## Key Patterns
- **No in-process session state** — all thread/message state is in PostgreSQL
- **Workspace isolation** — all DAO methods filter by `workspace_id`; cross-workspace access is impossible
- **Idempotent thread creation** — `get_or_create_thread` is safe to call on every request
- **Graceful LLM degradation** — MCP unavailability falls back to retrieval-only; only hard failures terminate
- **Hard-fail visibility filter** — any filter error aborts the request; no partial answers
- **Bounded tool-call loop** — `chat_max_tool_calls_per_request` (default 8) prevents infinite loops
