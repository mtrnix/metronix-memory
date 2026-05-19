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
`AsocMcpClient` — whitelist-gated MCP client that calls ASOC's streamable-HTTP MCP server
on behalf of an authenticated user.

Key behaviours:
- **Double-gate whitelist** — `ASOC_MCP_READ_ONLY_TOOLS_DEFAULT` (37 names) is the
  default; overridable via `METATRON_ASOC_MCP_ALLOWED_TOOLS`.  Both `list_available_tools`
  AND `invoke` check the gate; no write tool ever reaches the wire.
- **Per-user TTL cache** — `list_available_tools` caches per JWT-subject for
  `tool_list_cache_ttl_seconds` (default 60 s).  Soft cap 1024 entries; LRU-style
  eviction drops oldest 25 % when cap is exceeded.
- **JWT forwarding** — user JWT is forwarded verbatim as `Authorization: Bearer <jwt>`.
  T6 does NOT re-sign or inspect the JWT beyond extracting the `sub` claim for caching.
  Signature verification happens in T4 (`auth/asoc_jwt.py`).
- **Graceful degradation** — `list_available_tools` returns `[]` on network errors;
  callers fall back to retrieval-only mode.  `invoke` raises typed exceptions.
- **Retry** — `invoke` retries on 5xx/network up to `retry_attempts` (default 2) with
  exponential backoff (1 s, 2 s).  Auth errors (401/403) are never retried.

Exception hierarchy lives in this module (not in `core/exceptions.py`):
  `AsocMcpError` → `ToolNotAllowedError`, `McpAuthError`, `McpUnavailableError`,
  `McpProtocolError`.

### `asoc_visibility.py` (T5, MTRNIX-355)
`AsocVisibilityFilter` — POST-retrieval RBAC callback.  Calls ASOC's
`POST /api/v1/visibility/filter` under the user JWT and drops chunks whose parent
entity is NOT in `visible_ids`.

**Public API:**
```python
filter_chunks(user_jwt: str, merged_results: list[MergedResult])
    -> tuple[list[MergedResult], VisibilityFilterStats]
```
Returns `(filtered_results, stats)` preserving original ordering of allowed chunks.

**Design invariants:**
- **Hard-fail mode** — any HTTP failure raises a typed `VisibilityFilterError`.  Caller
  (T4 `AsocChatOrchestrator`) catches the base type and emits SSE `error: visibility_filter_failed`
  without invoking the LLM.  There is **no degraded-pass path** (security control).
- **5 s overall budget** enforced via `asyncio.wait_for` wrapping the full operation.
- **Parallel across resource types** (one `asyncio.gather` across resource type groups),
  sequential batching within each type.
- **Pass-through for non-ASOC chunks** — never calls the API for chunks with `source_type != "asoc"`.
- **No caching** of `visible_ids` per-user (Phase 2; staleness risk).
- **Empty JWT** raises `VisibilityFilterAuthError` immediately (no network call).

**Entity → resource_type mapping** (used to group chunks before calling ASOC):

| entity_type | resource_type sent to ASOC |
|-------------|---------------------------|
| `issue`, `comment`, `issue_history` | `issue` |
| `scan_result` | `scan_result` |
| `layer`, `sbom`, `dependency` | `layer` |
| `project`, `quality_gate`, `gate`, `event` | `project` |

**Exception hierarchy** (all in this module, not in `core/exceptions.py`):
```
VisibilityFilterError
├── VisibilityFilterConfigError  — asoc_base_url empty AND ASOC chunks present
├── VisibilityFilterAuthError    — 401/403 or empty JWT
├── VisibilityFilterUnavailableError — network / timeout / 5xx after retries
└── VisibilityFilterProtocolError   — 4xx (non-auth), malformed JSON, missing field
```

Construct via `AsocVisibilityFilter.from_settings(settings)`.

## Cooperation between T5 and T6
T4 (`AsocChatOrchestrator` in `chat/asoc_orchestrator.py`) calls both modules:

1. **Retrieval** → raw merged results from Qdrant.
2. **T5** → `AsocVisibilityFilter.filter_chunks(user_jwt, merged_results)` → drop invisible chunks.
   Hard-fail: if this raises `VisibilityFilterError`, T4 emits SSE error and returns — LLM is never called.
3. **T6** → `AsocMcpClient.list_available_tools(user_jwt)` → inject tool schemas into LLM prompt.
4. **LLM streaming** → LLM calls `cite_source` built-in OR selects an MCP tool.
5. **T6** → `AsocMcpClient.invoke(user_jwt, tool_name, arguments)` → proxy to ASOC MCP server.

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
