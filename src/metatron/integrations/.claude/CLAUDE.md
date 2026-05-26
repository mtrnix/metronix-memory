# Integrations

## Overview
L3 — thin HTTP/MCP clients for external services consumed by the ASOC pilot (epic
MTRNIX-340).  Modules here are stateless wrappers; they own no DB schema, no migration,
and no FastAPI route.  They are imported by higher layers (api/, agent/).

## Layer rule
`integrations/` is L3 — it may import from L0–L2 (core, storage, ingestion, retrieval)
but NEVER from L4–L6 (agent, channels, api).

## Modules

### `asoc_mcp_client.py` (T6, MTRNIX-356)
`AsocMcpClient` — whitelist-gated streamable-HTTP MCP client for ASOC.  Two modes:

- **admin mode** — sends `X-Api-Token: <ASOC_MCP_ADMIN_TOKEN>` only; no session.
  Used by `AsocConnector` (T1) for data ingestion via `asoc_list_*` / `asoc_get_*` tools.
- **user mode** — sends `X-Api-Token: <ASOC_MCP_ADMIN_TOKEN>` + `X-ASOC-Session: <session_id>`.
  Used by T4 (chat orchestrator) for user-context MCP calls and T5 (visibility filter).

Key behaviours:
- **Double-gate whitelist** — `ASOC_MCP_READ_ONLY_TOOLS_DEFAULT` (38 names: 37 LLM-visible
  + `asoc_visibility_filter` infra tool) is the default; overridable via
  `METATRON_ASOC_MCP_ALLOWED_TOOLS`.  Both `list_available_tools` AND `invoke` check
  the gate; no write tool ever reaches the wire.
- **Per-session TTL cache** — `list_available_tools` caches per `session_id` (used as
  cache key directly; no JWT decoding) for `tool_list_cache_ttl_seconds` (default 60 s).
  Soft cap 1024 entries; LRU-style eviction drops oldest 25 % when cap exceeded.
- **Session forwarding** — user-mode passes `session_id` as `X-ASOC-Session`.
  T6 does NOT inspect the session ID beyond using it as a stable cache key.
- **Graceful degradation** — `list_available_tools` returns `[]` on network errors;
  callers fall back to retrieval-only mode.  `invoke` raises typed exceptions.
- **Retry** — `invoke` retries on 5xx/network up to `retry_attempts` (default 2) with
  exponential backoff (1 s, 2 s).  Auth errors (401/403) are never retried.

Exception hierarchy lives in this module (not in `core/exceptions.py`):
  `AsocMcpError` → `ToolNotAllowedError`, `McpAuthError`, `McpUnavailableError`,
  `McpProtocolError`.

### `asoc_visibility.py` (T5, MTRNIX-355)
`AsocVisibilityFilter` — POST-retrieval RBAC callback.  Calls ASOC's
`asoc_visibility_filter` MCP tool via user-mode `AsocMcpClient` and drops chunks
whose parent entity is NOT in the response's `ids` array.

**Public API:**
```python
filter_chunks(session_id: str, merged_results: list[MergedResult])
    -> tuple[list[MergedResult], VisibilityFilterStats]
```
Returns `(filtered_results, stats)` preserving original ordering of allowed chunks.

**Design invariants:**
- **Hard-fail mode** — any MCP failure raises a typed `VisibilityFilterError`.  Caller
  (T4 `AsocChatOrchestrator`) catches the base type and emits SSE `error: visibility_filter_failed`
  without invoking the LLM.  There is **no degraded-pass path** (security control).
- **5 s overall budget** enforced via `asyncio.wait_for` wrapping the full operation.
- **Parallel across resource types** (one `asyncio.gather` across resource type groups),
  sequential batching within each type.
- **Pass-through for non-ASOC chunks** — never calls the MCP tool for chunks with
  `source_type != "asoc"`.
- **sbom guard** — chunks whose `entity_type` is a parent entity type (layer/sbom) are
  passed through directly; only leaf-level entities are sent to the filter.
- **No caching** of visible IDs per-user (Phase 2; staleness risk).
- **Empty session_id** raises `VisibilityFilterAuthError` immediately (no network call).
- **McpAuthError** → `VisibilityFilterAuthError` (not retried).
- **McpToolNotAllowedError** → `VisibilityFilterConfigError` (config bug; not retried).
- **McpUnavailableError / McpProtocolError** → retried up to `retry_attempts` times.

**Entity → resource_type mapping** (used to group chunks before calling the MCP tool;
see ASOC contract §1.1 — only `project|issue|scan|layer|gate` are valid resource types):

| entity_type | resource_type sent to ASOC |
|-------------|---------------------------|
| `issue`, `comment`, `issue_history` | `issue` |
| `scan_result` | `scan` |
| `layer`, `sbom`, `dependency` | `layer` |
| `quality_gate` (legacy alias), `gate` | `gate` |
| `project`, `event` | `project` |

**Exception hierarchy** (all in this module, not in `core/exceptions.py`):
```
VisibilityFilterError
├── VisibilityFilterConfigError  — mcp_client not configured / tool not in whitelist
├── VisibilityFilterAuthError    — McpAuthError or empty session_id
├── VisibilityFilterUnavailableError — McpUnavailableError after retries
└── VisibilityFilterProtocolError   — McpProtocolError / malformed response / missing ids field
```

Construct via `AsocVisibilityFilter.from_settings(settings, mcp_client=<user-mode client>)`.

## Cooperation between T5 and T6
T4 (`AsocChatOrchestrator` in `chat/asoc_orchestrator.py`) calls both modules:

1. **Retrieval** → raw merged results from Qdrant.
2. **T5** → `AsocVisibilityFilter.filter_chunks(session_id, merged_results)` → drop invisible chunks.
   Hard-fail: if this raises `VisibilityFilterError`, T4 emits SSE error and returns — LLM is never called.
3. **T6** → `AsocMcpClient.list_available_tools(session_id)` → inject tool schemas into LLM prompt.
4. **LLM streaming** → LLM calls `cite_source` built-in OR selects an MCP tool.
5. **T6** → `AsocMcpClient.invoke(session_id, tool_name, arguments)` → proxy to ASOC MCP server.

Neither T5 nor T6 knows about the other.  T4 owns the composition and error mapping:
- `VisibilityFilterError` → SSE `error: visibility_filter_failed`
- `McpAuthError` → SSE `error: llm_unavailable` (terminal)
- `McpUnavailableError` / `McpProtocolError` → SSE `tool_call: error` (non-terminal; LLM sees error message and can recover)

## Testing
Unit tests mock the MCP SDK session boundary, not raw httpx.  Mock the SDK's
`streamablehttp_client` context manager at the module import boundary so tests
stay SDK-version-agnostic.

Integration tests are skip-gated via `METATRON_ASOC_MCP_INTEGRATION_TEST_URL`
and marked `@pytest.mark.integration`.
