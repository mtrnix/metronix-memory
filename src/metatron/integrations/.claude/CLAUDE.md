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
`AsocVisibilityFilter` — POST-retrieval RBAC filter.  Calls ASOC's
`POST /api/v1/visibility/filter` under the user JWT and drops chunks whose parent
entity is not in `visible_ids`.  Hard-fail mode: returns an error sentinel on filter
failure; caller emits SSE `error: visibility_filter_failed` and skips the LLM stage.

## Cooperation between T5 and T6
T4 chat orchestrator calls both modules in sequence:
1. `AsocMcpClient.list_available_tools(user_jwt)` → inject tool schemas into LLM context.
2. LLM selects a tool → `AsocMcpClient.invoke(user_jwt, tool_name, arguments)`.
3. After retrieval → `AsocVisibilityFilter.filter(user_jwt, chunk_ids)`.

Neither T5 nor T6 knows about the other.  T4 owns the composition.

## Testing
Unit tests mock the MCP SDK session boundary, not raw httpx.  Mock the SDK's
`streamablehttp_client` context manager at the module import boundary so tests
stay SDK-version-agnostic.

Integration tests are skip-gated via `METATRON_ASOC_MCP_INTEGRATION_TEST_URL`
and marked `@pytest.mark.integration`.
