# ASOC Integration Guide

**Confluence reference:** [PILOT: Integration of Metronix with ASOC for AI Assistant and Workspace Management](https://mtrnix.atlassian.net/wiki/spaces/MTRNIX/pages/33783809)

**Epic:** MTRNIX-340 · **Pilot phase:** MVP (read-only, single-thread per user)

---

## 1. Overview

Metatron serves as the **chat orchestrator backend** for ASOC's project-view AI assistant. ASOC builds the user interface; Metatron handles everything backend: hybrid RAG retrieval over indexed project data, post-retrieval RBAC via the ASOC visibility/filter callback, LLM streaming with structured citations, persistent conversation threads, and live tool calls to ASOC's MCP server.

Data flows from ASOC into Metatron via a pull-based connector (`AsocConnector`). Metatron fetches ASOC entities (issues, scans, layers, comments, SBOM, quality gates, events) on a 15-minute delta-sync cadence and indexes them into a per-project Qdrant collection. Each ASOC project maps to exactly one Metatron workspace with the ID format `asoc-{instance_id}-{project_id}`.

Metatron does **not** duplicate ASOC's permission logic. After retrieval, Metatron calls `POST /api/v1/visibility/filter` on ASOC with the authenticated user's JWT and discards any chunk whose parent entity is absent from `visible_ids`. If the filter call fails for any reason, Metatron refuses to answer — no degraded path exists. This hard-fail mode is intentional: refusing is always safer than leaking.

---

## 2. Architecture Diagram

```
ASOC UI
  │
  │ POST /api/v1/asoc/chat  (ASOC-issued JWT, SSE response)
  ▼
Metatron API
  │
  ├─ asoc_jwt.py ────────────────── verify HMAC JWT → extract user_id, project_id
  │
  ├─ bootstrap_state lookup ──────── workspace state == READY?  (else SSE error)
  │
  ├─ rate_limit check ────────────── per-user token bucket
  │
  ├─ retrieval (hybrid search) ───── Qdrant collection mem_docs_hybrid_{workspace_id}
  │
  ├─ AsocVisibilityFilter ────────── POST /api/v1/visibility/filter  (ASOC)
  │     hard-fail if 5s budget exceeded or any error
  │
  ├─ AsocMcpClient.list_tools ────── GET tools from ASOC MCP server (cached 60s)
  │
  ├─ LLM streaming ───────────────── OpenAI-compat API with cite_source + MCP tools
  │     ├─ chunk events (text deltas)
  │     ├─ tool_call events (MCP invocations forwarded to ASOC MCP)
  │     └─ sources event (structured citation objects)
  │
  ├─ persist user + assistant messages (PostgreSQL)
  │
  └─ done event (always last)


ASOC Admin API calls (server-to-server, admin JWT):
  POST  /api/v1/workspace/bootstrap
  POST  /api/v1/workspace/{id}/archive
  POST  /api/v1/workspace/{id}/unarchive
  DELETE /api/v1/workspace/{id}
  GET   /api/v1/workspace/{id}/status
  DELETE /api/v1/users/{user_id}/chats
```

---

## 3. API Endpoints Exposed to ASOC

All endpoints are mounted under the Metatron base URL. Authentication is an ASOC-issued HMAC JWT in every request (see §4).

### Chat endpoints — user-facing, verified via ASOC JWT

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/asoc/chat` | Start a streaming chat. Returns SSE stream. |
| `GET` | `/api/v1/asoc/chat/threads` | List chat threads for the authenticated user in their workspace. |
| `GET` | `/api/v1/asoc/chat/threads/{id}/messages` | Fetch message history for a thread (oldest-first). Query params: `limit` (1–1000), `offset`. |
| `DELETE` | `/api/v1/asoc/chat/threads/{id}` | Delete a thread and all its messages (CASCADE). Returns 204. |

#### POST /api/v1/asoc/chat — request body

```json
{
  "message": "string (1–8192 chars, required)",
  "history": [{"role": "user|assistant", "content": "..."}]  // optional, injected into context
}
```

### Admin / server-to-server endpoints — verified via Metatron admin JWT

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/workspace/bootstrap` | Provision workspace and start full initial index. |
| `POST` | `/api/v1/workspace/{id}/archive` | Freeze ETL without deleting data (ready → archived). |
| `POST` | `/api/v1/workspace/{id}/unarchive` | Resume ETL (archived → ready). |
| `DELETE` | `/api/v1/workspace/{id}` | Cascade-delete workspace, index, and chat history. Idempotent, always 204. |
| `GET` | `/api/v1/workspace/{id}/status` | Read current bootstrap lifecycle state. |
| `DELETE` | `/api/v1/users/{user_id}/chats` | Cascade-delete all threads and messages for a user (call on user deletion). Returns 204. |

#### POST /api/v1/workspace/bootstrap — request body

```json
{
  "workspace_id": "asoc-{instance_id}-{project_id}",
  "source": "asoc",
  "config": {
    "url": "http://asoc-core:8080",
    "service_token": "<X-API-Token of Metatron_sync role>",
    "project_id": "<ASOC project UUID>",
    "asoc_instance_id": "<ASOC installation identifier>"
  }
}
```

Returns 202 on new workspace creation, 200 if already bootstrapping or ready, 409 if archived (unarchive first).

---

## 4. JWT Contract

ASOC issues HMAC-signed JWTs for every user request to Metatron. Metatron verifies them against the shared secret and never issues ASOC JWTs itself.

**Algorithm:** HS256 (or HS384/HS512 — see `ASOC_JWT_ALGORITHM`)

**Shared secret:** `ASOC_SHARED_SECRET` environment variable on the Metatron side

**Required claims:**

| Claim | Type | Description |
|-------|------|-------------|
| `user_id` | string | ASOC user identifier (or `sub` as fallback) |
| `project_id` | string | ASOC project UUID — used to derive `workspace_id` |
| `exp` | unix timestamp | Expiry — required, tokens without `exp` are rejected |

**Workspace derivation:**
```
workspace_id = "asoc-{METATRON_ASOC_INSTANCE_ID}-{project_id}"
```

`METATRON_ASOC_INSTANCE_ID` disambiguates multiple ASOC installations pointing at the same Metatron stack.

**Request header:**
```
Authorization: Bearer <jwt>
```

**Error responses:**
- `503` — `ASOC_SHARED_SECRET` not configured on Metatron
- `401 missing_bearer_token` — Authorization header missing or malformed
- `401 token_expired` — `exp` has passed
- `401 invalid_token` — bad signature, wrong algorithm, malformed header
- `401 missing_claim: ...` — `user_id`/`project_id` absent from verified payload

The raw JWT is forwarded verbatim as `Authorization: Bearer <jwt>` to both the visibility filter endpoint and every ASOC MCP tool call, so ASOC can enforce its own per-user RBAC at those layers too.

---

## 5. SSE Event Reference

The chat endpoint returns a `text/event-stream` (SSE) response. Events arrive in this order on a successful request:

```
status: {"status": "searching"}
status: {"status": "filtering"}
status: {"status": "answering"}
[status: {"status": "tool_calling"}]    ← 0..N times, interleaved with chunks
[tool_call: {"tool": "...", "status": "running"}]
[chunk: {"text": "<token>"}]            ← N incremental text tokens
[tool_call: {"tool": "...", "status": "done"|"error", "reason": "..."}]
[sources: {"sources": [...]}]           ← only when citations exist
done: {"workspace_id": "...", "thread_id": "..."}
```

**`done` is always the last event**, even on errors.

### Event payloads

| Event | Data shape | Purpose |
|-------|-----------|---------|
| `status` | `{"status": "searching"\|"filtering"\|"answering"\|"tool_calling"}` | Pipeline phase indicator for UI spinners |
| `chunk` | `{"text": "<incremental text>"}` | LLM streaming token |
| `sources` | `{"sources": [{...}]}` | Structured citation list (see below) |
| `tool_call` | `{"tool": "<name>", "status": "running"\|"done"\|"error", "reason": "..."}` | MCP tool invocation lifecycle |
| `done` | `{"workspace_id": "...", "thread_id": "..."|null}` | Terminal event |
| `error` | `{"code": "...", "message": "..."}` | Error — always followed by `done` |

### Citation object shape (in `sources` event)

```json
{
  "anchor": "[1]",
  "source_type": "issue|comment|issue_history|scan_result|layer|sbom|dependency|project|quality_gate|gate|event",
  "entity_id": "<UUID>",
  "display_id": "ASOC-1234",
  "title": "SQL injection in login handler",
  "url_hint": "/projects/{p}/issues/{i}"
}
```

### Error codes

| Code | Meaning |
|------|---------|
| `workspace_not_ready` | Workspace is still bootstrapping or in failed state |
| `rate_limited` | User exceeded `METATRON_CHAT_RATE_LIMIT_PER_MIN` |
| `visibility_filter_failed` | ASOC visibility/filter call failed or timed out — no answer returned |
| `llm_unavailable` | LLM endpoint unreachable, auth error, or tool-call loop exceeded |
| `timeout` | Full request exceeded `METATRON_CHAT_TIMEOUT_SECONDS` |

---

## 6. ASOC-Side Endpoint Requirements

Metatron calls the following ASOC endpoints. ASOC must implement them before the integration is functional.

### POST /api/v1/visibility/filter — **required, hard dependency**

Called after retrieval to enforce per-user RBAC. Metatron calls one batch per resource type.

**Request:**
```json
{
  "resource_type": "issue|scan_result|layer|project",
  "ids": ["<UUID>", ...]
}
```

**Response:**
```json
{
  "visible_ids": ["<UUID>", ...]
}
```

**Entity-to-resource-type mapping** (how Metatron groups chunk metadata):

| entity_type | resource_type sent to ASOC |
|-------------|---------------------------|
| `issue`, `comment`, `issue_history` | `issue` |
| `scan_result` | `scan_result` |
| `layer`, `sbom`, `dependency` | `layer` |
| `project`, `quality_gate`, `gate`, `event` | `project` |

**Hard-fail invariant: ASOC must respond within 5 seconds** (enforced by Metatron via `asyncio.wait_for`). Timeouts, 5xx, network errors → Metatron emits `error: visibility_filter_failed` and does not call the LLM. There is no degraded fallback.

Auth: Metatron forwards the original user JWT as `Authorization: Bearer <jwt>`.

Retry policy: up to 2 retries on 5xx/network errors per batch. Auth errors (401/403) are not retried.

### JWT issuance

ASOC must issue HMAC JWTs (HS256) with `user_id`, `project_id`, and `exp` claims using the shared secret set in `ASOC_SHARED_SECRET`.

### ASOC MCP server — optional but recommended

Metatron can call ASOC's MCP server at `ASOC_MCP_URL` for live operational data lookups during chat. ASOC must expose a streamable-HTTP MCP server with the 37 read-only tools in the whitelist (§9). Metatron forwards the user JWT on every MCP call. If the MCP server is absent or unreachable, chat falls back to retrieval-only mode gracefully.

---

## 7. Environment Configuration

All variables with an empty default must be set for the integration to work.

### JWT auth

| Variable | Default | Description |
|----------|---------|-------------|
| `ASOC_SHARED_SECRET` | `""` | HMAC secret shared with ASOC. Empty → `/api/v1/asoc/chat` returns 503 |
| `ASOC_JWT_ALGORITHM` | `HS256` | JWT algorithm. Must be HS256, HS384, or HS512 |
| `METATRON_ASOC_INSTANCE_ID` | `""` | Instance tag for workspace ID derivation: `asoc-{instance}-{project_id}` |

### ASOC REST API

| Variable | Default | Description |
|----------|---------|-------------|
| `ASOC_BASE_URL` | `""` | Base URL of the ASOC REST API (e.g. `http://asoc-core:8080`). Empty → visibility filter disabled (hard error on ASOC chunks) |

### ASOC MCP client

| Variable | Default | Description |
|----------|---------|-------------|
| `ASOC_MCP_URL` | `""` | URL of the ASOC MCP server. Empty → MCP client disabled, chat falls back to retrieval-only |
| `METATRON_ASOC_MCP_ALLOWED_TOOLS` | _(37 tools, see §9)_ | Comma-separated whitelist of MCP tool names. Write tools are never allowed regardless |
| `METATRON_ASOC_MCP_TOOL_LIST_CACHE_TTL_SECONDS` | `60.0` | Per-user tools/list cache TTL in seconds |
| `METATRON_ASOC_MCP_REQUEST_TIMEOUT_SECONDS` | `30.0` | Per-request timeout for tools/list and tools/call |
| `METATRON_ASOC_MCP_RETRY_ATTEMPTS` | `2` | Retry count on 5xx/network errors (0 = no retries) |

### Visibility filter tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `METATRON_ASOC_VISIBILITY_FILTER_TIMEOUT_SECONDS` | `5.0` | Hard overall budget for the filter step. Confluences §5 commits to 5s |
| `METATRON_ASOC_VISIBILITY_FILTER_BATCH_SIZE` | `100` | Max entity IDs per single visibility/filter POST |
| `METATRON_ASOC_VISIBILITY_FILTER_RETRY_ATTEMPTS` | `2` | Retry count on 5xx/network per batch |

### Bootstrap and sync

| Variable | Default | Description |
|----------|---------|-------------|
| `METATRON_ASOC_BOOTSTRAP_RETRY_MAX_ATTEMPTS` | `5` | Max retries for a failed BootstrapJob |
| `METATRON_ASOC_BOOTSTRAP_RETRY_BACKOFF_BASE_SECONDS` | `60.0` | Exponential backoff base: `base * 2^(attempt-1)` |
| `METATRON_ASOC_BOOTSTRAP_RETRY_INTERVAL_SECONDS` | `60` | Cron tick for the retry job (seconds) |
| `METATRON_ASOC_BOOTSTRAP_STALE_AFTER_SECONDS` | `600` | Bootstrapping rows older than this at startup are reclaimed |
| `METATRON_ASOC_SYNC_MAX_CONCURRENT_WORKSPACES` | `3` | Semaphore cap on parallel delta-syncs |
| `METATRON_ASOC_SYNC_INTERVAL_SECONDS` | `900` | Delta-sync cron interval in seconds (default 15 min) |

### Chat history

| Variable | Default | Description |
|----------|---------|-------------|
| `METATRON_CHAT_HISTORY_RETENTION_DAYS` | `90` | Retention cutoff for chat messages (cleanup cron) |
| `METATRON_CHAT_HISTORY_TURNS_IN_CONTEXT` | `10` | Last N turns injected into the prompt |
| `METATRON_CHAT_HISTORY_MAX_TOKENS_IN_CONTEXT` | `4000` | Token cap on injected history |
| `METATRON_CHAT_HISTORY_CLEANUP_INTERVAL_SECONDS` | `86400` | Sleep interval between cleanup worker passes |

### Chat orchestrator

| Variable | Default | Description |
|----------|---------|-------------|
| `METATRON_CHAT_RATE_LIMIT_PER_MIN` | `30` | Requests per minute per user (token bucket) |
| `METATRON_CHAT_TIMEOUT_SECONDS` | `30.0` | Hard timeout for the full chat request |
| `METATRON_CHAT_MAX_TOOL_CALLS_PER_REQUEST` | `8` | Maximum LLM→MCP tool-call loop iterations |
| `METATRON_CHAT_CONTEXT_MAX_CHARS` | `24000` | Character cap on retrieved context injected into the prompt |

### Chat LLM (OpenAI-compatible)

| Variable | Default | Description |
|----------|---------|-------------|
| `METATRON_CHAT_API_BASE` | `""` | Base URL of the OpenAI-compatible LLM endpoint (e.g. `https://api.openai.com/v1` or `http://vllm:8000/v1`). Empty → `llm_unavailable` error |
| `METATRON_CHAT_API_KEY` | `""` | API key for the chat LLM endpoint |
| `METATRON_CHAT_MODEL` | `gpt-4o-mini` | Chat model name (e.g. `gpt-4o-mini`, `Qwen2.5-72B-Instruct`) |
| `METATRON_CHAT_TEMPERATURE` | `0.1` | LLM temperature (0.0–2.0) |
| `METATRON_CHAT_MAX_TOKENS` | `4096` | Max tokens in LLM response |

---

## 8. Workspace Lifecycle

ASOC drives the workspace lifecycle by calling the admin endpoints. Metatron manages the `bootstrap_state` table internally.

### State machine

```
                     POST /workspace/bootstrap
                              │
                              ▼
              ┌───────────────────────────────┐
              │         bootstrapping          │ ◄── resumable; checkpoint saved per batch
              └───────────────────────────────┘
                      │              │
              success │              │ failure
                      ▼              ▼
              ┌──────────┐    ┌──────────┐
              │  ready   │    │  failed  │ ◄── auto-retry with exponential backoff
              └──────────┘    └──────────┘
                 │    ▲              │
  POST /archive  │    │  POST /unarchive
                 ▼    │
              ┌──────────┐
              │ archived │
              └──────────┘
                   │
      DELETE /{id} │  (also valid from any state)
                   ▼
                 (gone)
```

### Status response shape

`GET /workspace/{id}/status` returns:

```json
{
  "workspace_id": "asoc-prod-{project_id}",
  "state": "bootstrapping|ready|archived|failed",
  "progress": 0.65,
  "current_step": "issues",
  "indexed_count": 1240,
  "total_count": 1900,
  "last_synced_at": "2026-05-19T12:00:00Z",
  "last_error": null,
  "retry_count": 0,
  "next_retry_at": null,
  "updated_at": "2026-05-19T12:01:00Z"
}
```

### ASOC responsibilities

- Call `POST /workspace/bootstrap` when admin enables the AI assistant for a project.
- Poll `GET /workspace/{id}/status` for readiness before showing the chat UI.
- Call `POST /workspace/{id}/archive` / `unarchive` on project lifecycle events.
- Call `DELETE /workspace/{id}` when removing a project permanently.
- Call `DELETE /users/{user_id}/chats` when deleting an ASOC user (GDPR cascade).

Metatron handles resume automatically: if bootstrap is interrupted (crash, deploy), the retry cron picks up from the last saved checkpoint (`last_processed_resource` / `last_processed_id`).

---

## 9. MCP Tool Whitelist (37 read-only tools)

These are the tools Metatron exposes to the LLM. Write tools (15 total) are blocked at both the `list_available_tools` and `invoke` layers — they never reach the wire in MVP.

```
asoc_list_issues              asoc_get_issue
asoc_count_issues             asoc_list_issue_statuses
asoc_get_issue_available_transitions
asoc_get_issue_comments       asoc_get_issue_history
asoc_get_issues_categories    asoc_get_issues_filters
asoc_list_projects            asoc_get_project
asoc_get_project_layer_tree   asoc_list_layers
asoc_get_layer                asoc_list_scan_results
asoc_get_scan_stats           asoc_compare_scan_results
asoc_list_security_checks     asoc_get_security_check
asoc_get_stats_all            asoc_get_stats_severity
asoc_get_stats_by_tool        asoc_get_stats_projects
asoc_get_integral_risk        asoc_get_defect_time
asoc_list_sboms               asoc_list_dependencies
asoc_get_dependency           asoc_list_trackers
asoc_get_tracker_task_types   asoc_list_users
asoc_list_groups              asoc_get_profile
asoc_list_quality_gates       asoc_get_layer_gates
asoc_list_events              asoc_get_copilot_fp_analysis
```

The default whitelist is defined in `src/metatron/core/asoc_constants.py::ASOC_MCP_READ_ONLY_TOOLS_DEFAULT`. Override via `METATRON_ASOC_MCP_ALLOWED_TOOLS` (comma-separated; all names must start with `asoc_`).

Write tools (status changes, scan triggers, suppression) are deferred to Phase 2 pending a HITL review UI and prompt-injection audit.

---

## 10. Limitations (MVP)

These constraints are intentional in the pilot. Phase 2 plans are noted where applicable.

- **No write tools in chat.** All 15 ASOC-MCP write tools are blocked. Enabling requires HITL UI + prompt-injection audit.
- **One thread per (user, workspace).** Multi-thread support is a Phase 2 item.
- **No caching of visibility results.** Every request calls ASOC's filter endpoint. Caching with short TTL is a Phase 2 item (staleness risk).
- **Pull-only sync (15-min latency).** New issues/scans added to ASOC may not be in the index for up to 15 minutes. Use MCP live tools for current operational data. Webhook push sync is Phase 2.
- **No degraded path on filter failure.** If the visibility filter is unavailable, the chat request fails. This is a security control.
- **Embedding model change is destructive.** Changing `METATRON_EMBEDDING_MODEL` or dimension requires dropping and re-bootstrapping all Qdrant collections. Changing `METATRON_CHAT_MODEL` is safe.
- **No semantic search over chat history.** History is retrieved linearly (last N turns).
- **No chat export or sharing.** Phase 2.
- **No prompt-injection protection** through issue content. Read-only mode keeps the risk low; formal protection is Phase 2.
- **Multi-replica race protection** (bootstrap cron, sync cron) is not implemented. MVP is single-replica; Phase 2 will add distributed locking.

---

## 11. Open Questions (pending ASOC team confirmation)

- **`updated_after` per-endpoint support:** Confluence §5 flags this as "requires confirmation". If ASOC REST endpoints don't support `updated_after` on every entity type, Metatron will fall back to full pull with delta computed via content-hash dedup (inefficient).
- **Field naming:** Confluence §4 uses both `gate` and `quality_gate` as entity types. The mapping in `asoc_visibility.py` handles both as defensive aliases — confirm the canonical name in ASOC's API.
- **Severity numeric encoding:** confirm whether severity `-1` is a valid value and what it means (currently mapped as any other numeric severity).
- **MCP tool list stability:** confirm the 37-tool whitelist matches ASOC's ASOCDEV-2182 release.
- **JWT rotation procedure:** confirm how ASOC rotates `ASOC_SHARED_SECRET` and whether a rolling-rotation window is needed.

---

## 12. Operational Playbook

### Bootstrap a new workspace

```bash
# 1. Generate a workspace ID (deterministic format)
WS_ID="asoc-prod-${PROJECT_UUID}"

# 2. Call bootstrap (admin JWT required)
curl -X POST https://metatron.example.com/api/v1/workspace/bootstrap \
  -H "Authorization: Bearer <admin_jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "'$WS_ID'",
    "source": "asoc",
    "config": {
      "url": "http://asoc-core:8080",
      "service_token": "<metatron_sync_token>",
      "project_id": "'$PROJECT_UUID'",
      "asoc_instance_id": "prod"
    }
  }'

# 3. Poll until ready
curl https://metatron.example.com/api/v1/workspace/$WS_ID/status \
  -H "Authorization: Bearer <admin_jwt>"
```

### Archive / unarchive a workspace

```bash
curl -X POST https://metatron.example.com/api/v1/workspace/$WS_ID/archive \
  -H "Authorization: Bearer <admin_jwt>"

curl -X POST https://metatron.example.com/api/v1/workspace/$WS_ID/unarchive \
  -H "Authorization: Bearer <admin_jwt>"
```

### Troubleshoot a failed bootstrap

Check `bootstrap_state.last_error` via the status endpoint:
```bash
curl https://metatron.example.com/api/v1/workspace/$WS_ID/status \
  -H "Authorization: Bearer <admin_jwt>"
# Look at: state, last_error, retry_count, next_retry_at
```

The retry cron (60s tick) will automatically re-attempt using the saved checkpoint. If you need to force a retry immediately, call `POST /workspace/bootstrap` again — it is idempotent and will re-enter `bootstrapping` state.

### Force a delta sync

Metatron does not expose a manual sync trigger for ASOC workspaces in MVP. The automatic sync runs every `METATRON_ASOC_SYNC_INTERVAL_SECONDS` (default 15 min) for all `ready` workspaces. For urgent reindexing, use `DELETE /workspace/{id}` + `POST /workspace/bootstrap` (full re-index, discards existing data).

### View or clear chat history

```bash
# List threads for a user (requires the user's ASOC JWT)
curl https://metatron.example.com/api/v1/asoc/chat/threads \
  -H "Authorization: Bearer <user_asoc_jwt>"

# Delete a specific thread
curl -X DELETE https://metatron.example.com/api/v1/asoc/chat/threads/<thread_id> \
  -H "Authorization: Bearer <user_asoc_jwt>"

# Cascade-delete all chats for a deleted user (admin)
curl -X DELETE https://metatron.example.com/api/v1/users/<user_id>/chats \
  -H "Authorization: Bearer <admin_jwt>"
```

---

## 13. Deployment

Metatron is delivered as a **standalone docker-compose stack**, independent of ASOC. The ASOC stack only needs to know the Metatron URL and the shared secret.

Minimum services:

```yaml
services:
  metatron-core:
    image: metatron/core:latest
    environment:
      # Required for ASOC integration
      ASOC_SHARED_SECRET: "${ASOC_SHARED_SECRET}"
      ASOC_BASE_URL: "http://asoc-core:8080"
      ASOC_MCP_URL: "http://asoc-core:8080/mcp"
      METATRON_ASOC_INSTANCE_ID: "prod"
      # LLM (example: OpenAI)
      METATRON_CHAT_API_BASE: "https://api.openai.com/v1"
      METATRON_CHAT_API_KEY: "${OPENAI_API_KEY}"
      METATRON_CHAT_MODEL: "gpt-4o-mini"
      # Embeddings (example: hosted TEI)
      METATRON_EMBEDDING_API_BASE: "http://tei:8080/v1"
      METATRON_EMBEDDING_MODEL: "bge-m3"
      METATRON_EMBEDDING_DIMENSION: "1024"
      # PostgreSQL
      POSTGRES_HOST: "postgres-metatron"
      POSTGRES_DB: "metatron"
      POSTGRES_USER: "metatron"
      POSTGRES_PASSWORD: "${PG_PASSWORD}"
    ports:
      - "8000:8000"

  postgres-metatron:
    image: postgres:16
    environment:
      POSTGRES_DB: metatron
      POSTGRES_USER: metatron
      POSTGRES_PASSWORD: "${PG_PASSWORD}"

  qdrant:
    image: qdrant/qdrant:v1.16.0
    ports:
      - "6333:6333"

  neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: "neo4j/${NEO4J_PASSWORD}"

  tei:  # optional — self-hosted embeddings
    image: ghcr.io/huggingface/text-embeddings-inference:latest
    command: --model-id BAAI/bge-m3
```

For customers using Metatron beyond ASOC (e.g. as memory backbone for other agents), a single Metatron stack serves all sources. ASOC is one connector among many.
