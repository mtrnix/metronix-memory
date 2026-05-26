# ASOC Integration Guide

**Confluence reference:** [PILOT: Integration of Metronix with ASOC for AI Assistant and Workspace Management](https://mtrnix.atlassian.net/wiki/spaces/MTRNIX/pages/33783809)

**Epic:** MTRNIX-340 · **Canonical contract:** `docs/ASOC_API_CONTRACT.md`

**Status:** Phase 1–3 complete (MTRNIX-370 rework). Auth is session_id + static shared token.
JWT-based auth (`ASOC_SHARED_SECRET` / `ASOC_JWT_ALGORITHM`) has been removed.

---

## 1. Overview

Metatron serves as the **chat orchestrator backend** for ASOC's project-view AI assistant. ASOC builds the UI; Metatron handles everything backend: hybrid RAG retrieval over indexed project data, post-retrieval visibility filtering via ASOC MCP, LLM streaming with structured citations, persistent conversation threads, and live tool calls to ASOC's MCP server.

Data flows from ASOC into Metatron exclusively via MCP. Metatron fetches ASOC entities (issues, scans, layers, comments, SBOM, quality gates, events) on a 15-minute delta-sync cadence using admin-mode MCP calls and indexes them into a per-project Qdrant collection. Each ASOC project maps to exactly one Metatron workspace with the ID format `asoc-{instance_id}-{project_id}`.

For the canonical request/response shapes that the ASOC dev team integrates against, see **`docs/ASOC_API_CONTRACT.md`**. This guide is for Metatron developers and operators.

---

## 2. Architecture Diagram

```
ASOC frontend
  │
  │  POST /api/v1/asoc/chat  (X-ASOC-Session: <session_id>)
  ▼
Metatron API
  │
  ├─ auth/asoc_session.py ──── validate session_id via in-process TTL cache
  │      (cache miss → asoc_get_current_user MCP call → AsocAuthContext cached)
  │
  ├─ bootstrap_state check ──── workspace READY? (else SSE error)
  │
  ├─ rate-limit ──────────────── per-user token bucket
  │
  ├─ retrieval ───────────────── Qdrant hybrid search (async)
  │
  ├─ T5 AsocVisibilityFilter ── asoc_visibility_filter MCP tool (user mode)
  │      hard-fail: 5s budget, no degraded path
  │
  ├─ T6 AsocMcpClient ────────── asoc_list_available_tools (user mode, cached 60s)
  │
  ├─ LLM streaming ───────────── OpenAI-compat, cite_source + 37 ASOC MCP tools
  │      ├─ chunk events (text deltas)
  │      ├─ tool_call events (MCP invocations via T6 user mode)
  │      └─ sources event (structured citation objects)
  │
  ├─ persist user + assistant messages (PostgreSQL)
  │
  └─ done event (always last)


ASOC backend → Metatron (admin channel):
  Authorization: Bearer <ASOC_MCP_ADMIN_TOKEN>
  POST   /api/v1/workspace/bootstrap
  DELETE /api/v1/workspace/{id}
  GET    /api/v1/workspace/{id}/status
  DELETE /api/v1/users/{user_id}/chats


Metatron → ASOC MCP server (data pull — admin mode):
  X-Api-Token: <ASOC_MCP_ADMIN_TOKEN>
  asoc_list_projects / asoc_list_issues / asoc_list_layers / …
  (15-min delta sync, pagination via cursor / next_cursor)
```

---

## 3. Auth Model

Two auth modes; both use the same shared token (`ASOC_MCP_ADMIN_TOKEN`). Full details in
`docs/ASOC_API_CONTRACT.md §1` and `§3`.

### 3.1 Admin channel (ASOC backend → Metatron)

```http
Authorization: Bearer <ASOC_MCP_ADMIN_TOKEN>
```

Used for workspace lifecycle endpoints and user-cascade delete. Returns 401 on
missing/wrong header; 503 if `ASOC_MCP_ADMIN_TOKEN` is empty (operator mis-config).

### 3.2 Chat channel (ASOC frontend → Metatron)

```http
X-ASOC-Session: <user_session_id>
```

The session_id is the user's active ASOC session cookie value. Metatron validates it via
`asoc_get_current_user` (user-mode MCP call) and caches the result for
`METATRON_ASOC_SESSION_CACHE_TTL_SECONDS` (default 3600 s). CORS must be configured via
`METATRON_ASOC_ALLOWED_ORIGINS` so the frontend can reach Metatron directly.

### 3.3 Metatron → ASOC MCP (data pull and live tools)

Admin mode (T1 connector sync):
```
X-Api-Token: <ASOC_MCP_ADMIN_TOKEN>
```

User mode (T5 visibility filter, T6 tool calls):
```
X-Api-Token: <ASOC_MCP_ADMIN_TOKEN>
X-ASOC-Session: <user_session_id>
```

---

## 4. Environment Configuration

Variables marked **required** must be set for the integration to function.

### Core auth and connection

| Variable | Default | Notes |
|----------|---------|-------|
| `ASOC_MCP_URL` | `""` | **Required.** ASOC MCP server URL (e.g. `http://asoc-core:8080/mcp`). Empty → chat route returns 503. |
| `ASOC_MCP_ADMIN_TOKEN` | `""` | **Required.** Shared static token. Empty → admin routes and connector sync return 503. |
| `METATRON_ASOC_INSTANCE_ID` | `""` | **Required.** Instance tag: `workspace_id = asoc-{instance}-{project_id}`. |
| `METATRON_ASOC_ALLOWED_ORIGINS` | `[]` | CSV of ASOC frontend origins for CORS (`allow_credentials=True`). |
| `METATRON_ASOC_SESSION_CACHE_TTL_SECONDS` | `3600.0` | TTL for `session_id → user identity` in-process cache. |

### MCP client tuning

| Variable | Default | Notes |
|----------|---------|-------|
| `METATRON_ASOC_MCP_ALLOWED_TOOLS` | _(38 names, see §7)_ | Comma-separated whitelist. All names must start with `asoc_`. |
| `METATRON_ASOC_MCP_TOOL_LIST_CACHE_TTL_SECONDS` | `60.0` | Per-session LLM tool list cache TTL. |
| `METATRON_ASOC_MCP_REQUEST_TIMEOUT_SECONDS` | `30.0` | Per-MCP-request timeout. |
| `METATRON_ASOC_MCP_RETRY_ATTEMPTS` | `2` | Retries on 5xx/network (0 = no retries). |

### Visibility filter

| Variable | Default | Notes |
|----------|---------|-------|
| `METATRON_ASOC_VISIBILITY_FILTER_TIMEOUT_SECONDS` | `5.0` | Hard overall budget for the filter step. Hard-fail if exceeded. |
| `METATRON_ASOC_VISIBILITY_FILTER_BATCH_SIZE` | `100` | Max entity IDs per `asoc_visibility_filter` MCP call. |
| `METATRON_ASOC_VISIBILITY_FILTER_RETRY_ATTEMPTS` | `2` | Retries on MCP unavailability per batch. |

### Bootstrap and sync

| Variable | Default | Notes |
|----------|---------|-------|
| `METATRON_ASOC_BOOTSTRAP_RETRY_MAX_ATTEMPTS` | `5` | Max retries for a failed BootstrapJob. |
| `METATRON_ASOC_BOOTSTRAP_RETRY_BACKOFF_BASE_SECONDS` | `60.0` | Backoff base: `base × 2^(attempt-1)`. |
| `METATRON_ASOC_BOOTSTRAP_RETRY_INTERVAL_SECONDS` | `60` | Bootstrap retry cron tick (seconds). |
| `METATRON_ASOC_BOOTSTRAP_STALE_AFTER_SECONDS` | `600` | Bootstrapping rows older than this are reclaimed at startup. |
| `METATRON_ASOC_SYNC_MAX_CONCURRENT_WORKSPACES` | `3` | Parallel delta-sync concurrency cap. |
| `METATRON_ASOC_SYNC_INTERVAL_SECONDS` | `900` | Delta-sync cron interval (default 15 min). |

### Chat history and orchestrator

| Variable | Default | Notes |
|----------|---------|-------|
| `METATRON_CHAT_HISTORY_RETENTION_DAYS` | `90` | Message retention cutoff for the cleanup cron. |
| `METATRON_CHAT_HISTORY_TURNS_IN_CONTEXT` | `10` | Last N turns injected into the prompt. |
| `METATRON_CHAT_HISTORY_MAX_TOKENS_IN_CONTEXT` | `4000` | Token cap on injected history. |
| `METATRON_CHAT_HISTORY_CLEANUP_INTERVAL_SECONDS` | `86400` | Sleep between cleanup worker passes. |
| `METATRON_CHAT_RATE_LIMIT_PER_MIN` | `30` | Requests/minute per user (token bucket). |
| `METATRON_CHAT_TIMEOUT_SECONDS` | `30.0` | Hard timeout for the full chat request. |
| `METATRON_CHAT_MAX_TOOL_CALLS_PER_REQUEST` | `8` | Max LLM→MCP tool-call iterations per request. |
| `METATRON_CHAT_CONTEXT_MAX_CHARS` | `24000` | Char cap on retrieved context in prompt. |

### Chat LLM

| Variable | Default | Notes |
|----------|---------|-------|
| `METATRON_CHAT_API_BASE` | `""` | **Required.** OpenAI-compat LLM base URL. Empty → `llm_unavailable` SSE error. |
| `METATRON_CHAT_API_KEY` | `""` | API key for the chat LLM. |
| `METATRON_CHAT_MODEL` | `gpt-4o-mini` | Chat model name. |
| `METATRON_CHAT_TEMPERATURE` | `0.1` | LLM temperature (0.0–2.0). |
| `METATRON_CHAT_MAX_TOKENS` | `4096` | Max tokens in LLM response. |

---

## 5. Workspace Lifecycle

ASOC drives the workspace lifecycle. Metatron manages the `bootstrap_state` table internally.
Full endpoint reference in `docs/ASOC_API_CONTRACT.md §2`.

### State machine

```
                POST /workspace/bootstrap
                         │
                         ▼
         ┌───────────────────────────────┐
         │         bootstrapping          │ ← resumable via checkpoint
         └───────────────────────────────┘
                 │              │
         success │              │ failure
                 ▼              ▼
         ┌──────────┐    ┌──────────┐
         │  ready   │    │  failed  │ ← auto-retry with exponential backoff
         └──────────┘    └──────────┘
              │
  DELETE /{id}│  (valid from any state)
              ▼
            (gone)
```

No separate archive/unarchive states. ASOC backend calls `DELETE /workspace/{id}` on
project archive events; re-enabling requires a fresh `POST /workspace/bootstrap`.

### Bootstrap a workspace

```bash
curl -X POST http://metatron:8000/api/v1/workspace/bootstrap \
  -H "Authorization: Bearer $ASOC_MCP_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "asoc-prod-'$PROJECT_UUID'",
    "source": "asoc",
    "config": {
      "url": "http://asoc-core:8080",
      "service_token": "'$ASOC_MCP_ADMIN_TOKEN'",
      "project_id": "'$PROJECT_UUID'",
      "asoc_instance_id": "prod"
    }
  }'

# Poll until ready
curl http://metatron:8000/api/v1/workspace/asoc-prod-$PROJECT_UUID/status \
  -H "Authorization: Bearer $ASOC_MCP_ADMIN_TOKEN"
```

### Delete a workspace

```bash
curl -X DELETE http://metatron:8000/api/v1/workspace/asoc-prod-$PROJECT_UUID \
  -H "Authorization: Bearer $ASOC_MCP_ADMIN_TOKEN"
# Returns 204 always (idempotent)
```

---

## 6. Chat Flow

High-level steps for a single `POST /api/v1/asoc/chat` request:

1. **Auth** — `asoc_session_auth.validate(session_id)` → hit in-process cache or call `asoc_get_current_user` via user-mode MCP → `AsocAuthContext(user_id, project_id, session_id)`.
2. **Workspace check** — `asoc-{instance}-{project_id}` must be in `READY` state.
3. **Rate limit** — per-user token bucket (`METATRON_CHAT_RATE_LIMIT_PER_MIN`).
4. **Thread** — `get_or_create_thread(workspace_id, user_id)` (one per user per workspace in MVP).
5. **Retrieval** — hybrid search over `mem_docs_hybrid_{workspace_id}` Qdrant collection.
6. **Visibility filter** — `AsocVisibilityFilter.filter_chunks(session_id, results)` via `asoc_visibility_filter` MCP tool. Hard-fail: 5 s budget, any error → SSE `error: visibility_filter_failed`, no LLM call.
7. **Tool list** — `AsocMcpClient.list_available_tools(session_id)` (cached 60 s). Graceful degradation to retrieval-only on failure.
8. **Prompt assembly** — system prompt + conversation history + retrieved context.
9. **LLM streaming** — OpenAI-compat chat completions with `cite_source` built-in + 37 ASOC MCP tools. Bounded tool-call loop (`METATRON_CHAT_MAX_TOOL_CALLS_PER_REQUEST`).
10. **Persist** — user message and assistant message saved to PostgreSQL.
11. **SSE `done`** — always the last event.

SSE event reference and citation object shape: `docs/ASOC_API_CONTRACT.md §4`.

---

## 7. MCP Tool Whitelist

The `ASOC_MCP_READ_ONLY_TOOLS_DEFAULT` constant (38 names) is defined in
`src/metatron/core/asoc_constants.py`. 37 of these are exposed to the LLM; one
(`asoc_visibility_filter`) is an infra tool used by T5 only.

Override via `METATRON_ASOC_MCP_ALLOWED_TOOLS` (comma-separated; all names must start with `asoc_`).

Write tools (status changes, scan triggers, suppression) are deferred to Phase 2 pending
a HITL review UI and prompt-injection audit.

---

## 8. Operational Notes

### Log lines to watch

| log key | meaning |
|---------|---------|
| `asoc.session.cache_miss` | session_id not cached; MCP identity lookup fired |
| `asoc.session.validate_failed` | identity lookup failed; request → 401 |
| `asoc.visibility_filter.result` | chunks passed / dropped count |
| `asoc.visibility_filter.timeout` | filter exceeded 5 s budget |
| `asoc.mcp.tools_list.fetched` | tool list fetched from ASOC MCP |
| `asoc.mcp.invoke.error` | MCP tool call failed |
| `asoc.connector.sync.complete` | delta sync finished for a workspace |
| `asoc.bootstrap.job.complete` | full bootstrap finished |
| `asoc.bootstrap.job.failed` | bootstrap failed; retry scheduled |

### Common error modes

**503 on chat endpoint** — `ASOC_MCP_URL` or `ASOC_MCP_ADMIN_TOKEN` not set.

**SSE `error: workspace_not_ready`** — bootstrap still running or in `failed` state.
Check `GET /workspace/{id}/status` → `last_error` field.

**SSE `error: visibility_filter_failed`** — ASOC MCP server unreachable or `asoc_visibility_filter`
tool not in whitelist. Check `ASOC_MCP_URL` connectivity and `METATRON_ASOC_MCP_ALLOWED_TOOLS`.

**SSE `error: llm_unavailable`** — LLM endpoint (`METATRON_CHAT_API_BASE`) unreachable
or chat LLM returned auth error.

**Delta sync lag** — new ASOC entities are indexed with up to `METATRON_ASOC_SYNC_INTERVAL_SECONDS`
(default 15 min) latency. Use live MCP tool calls for current operational data during chat.

### Rate limits

- Chat: `METATRON_CHAT_RATE_LIMIT_PER_MIN` (default 30 req/min/user). In-process token bucket; not shared across replicas (MVP single-replica only).

---

## 9. Migration from JWT-Based Setup

Previous versions (before MTRNIX-370) used HS256 HMAC JWTs issued by ASOC and verified via
`ASOC_SHARED_SECRET` / `ASOC_JWT_ALGORITHM`. This has been removed entirely.

**Remove from Metatron environment:**
- `ASOC_SHARED_SECRET`
- `ASOC_JWT_ALGORITHM`
- `ASOC_BASE_URL` (REST base URL, no longer used)

**Add to Metatron environment:**
- `ASOC_MCP_URL` — ASOC MCP server URL
- `ASOC_MCP_ADMIN_TOKEN` — static shared token (replaces `ASOC_SHARED_SECRET`)
- `METATRON_ASOC_ALLOWED_ORIGINS` — CORS origins for ASOC frontend

**ASOC frontend change:** replace `Authorization: Bearer <jwt>` with `X-ASOC-Session: <session_id>`.

---

## 10. MVP Limitations

- **No write tools.** All ASOC MCP write tools are blocked. Enabling requires HITL UI + prompt-injection audit (Phase 2).
- **One thread per (user, workspace).** Multi-thread support is Phase 2.
- **No visibility result caching.** Every request calls `asoc_visibility_filter`. Per-request caching is Phase 2.
- **Pull-only sync (15-min latency).** New ASOC entities may not be indexed for up to 15 min. Use live MCP tools for real-time data.
- **No degraded path on visibility filter failure.** Visibility unavailable → request fails. Intentional security control.
- **No multi-replica coordination.** Bootstrap and sync crons are single-process; distributed locking is Phase 2.
