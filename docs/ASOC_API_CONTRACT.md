# ASOC ↔ Metatron API Contract

This document describes the network contract between **ASOC** and **Metatron** for the AI-assistant pilot. It is the canonical reference for the ASOC dev team to integrate against.

Architecture summary (per grooming sessions 2026-05):

- **Metatron** is a chat-orchestrator backend behind ASOC's project-view AI assistant.
- **ASOC** owns the UI (side panel chat widget, project settings page).
- **All ASOC ↔ Metatron communication uses two channels:**
  - HTTP for control-plane (bootstrap, lifecycle, chat) — ASOC initiates
  - MCP for data-plane (entity sync, live tool-use, visibility filtering) — Metatron initiates
- One workspace per ASOC project. Workspaces are isolated; an assistant only sees its own project.

---

## 1. Channels overview

| Direction | Transport | Auth headers | Purpose |
|---|---|---|---|
| ASOC backend → Metatron | HTTP | `Authorization: Bearer <ASSISTANT_ASOC_TO_METRONIX_TOKEN>` | Workspace lifecycle (bootstrap / delete / status), user cascade |
| ASOC frontend → Metatron | HTTP + SSE | `X-ASOC-Session: <session_id>` | Chat orchestration (POST /chat), thread management |
| Metatron → ASOC MCP | MCP (admin mode) | `X-Api-Token: <ASSISTANT_ASOC_TO_METRONIX_TOKEN>` | Initial bootstrap + periodic delta sync of project entities (acts as system user `metatron` with `isadm` role) |
| Metatron → ASOC MCP | MCP (user mode) | `X-Api-Token: <ASSISTANT_ASOC_TO_METRONIX_TOKEN>` + `X-ASOC-Session: <user_session_id>` | Live tool-calls during chat, visibility filtering (acts under user's RBAC) |
| Metatron → ASOC | HTTP | TBD | Optional `session_ok` callback for session validation (decision pending — see §9) |

**Single token, three uses.** The same predefined token value (`ASSISTANT_ASOC_TO_METRONIX_TOKEN` on ASOC side = `ASOC_MCP_ADMIN_TOKEN` on Metatron side) covers:
- ASOC backend → Metatron HTTP: as `Authorization: Bearer <token>`
- Metatron → ASOC MCP (any mode): as `X-Api-Token: <token>`

On ASOC side this token belongs to a predefined system user named `metatron` (created via DB migration, role `isadm`). When Metatron calls the MCP server with `X-Api-Token + X-ASOC-Session`, ASOC's `withAuth` middleware verifies the token matches the metatron-system-user's token (constant-time compare) and then resolves the session_id to build RBAC context as the real user.

**No JWT.** Earlier design used HS256 JWTs; revised approach uses static shared tokens + ASOC session_id directly. Simpler operationally.

---

## 2. ASOC → Metatron — HTTP endpoints

All endpoints prefixed `/api/v1/`. Metatron's base URL is configured on the ASOC backend (e.g. `METATRON_URL=http://metatron:8000`).

### 2.1 Admin endpoints (admin channel)

Auth: every request includes `Authorization: Bearer <token>` where `<token>` is the predefined ASOC system token (`ASSISTANT_ASOC_TO_METRONIX_TOKEN` on ASOC side, `ASOC_ADMIN_TOKEN` on Metatron side — same value). 401 on missing/wrong header. 503 if Metatron's `ASOC_ADMIN_TOKEN` env is empty (operator misconfig).

| Method | Path | Purpose | Response |
|---|---|---|---|
| `POST` | `/workspace/bootstrap` | Enable assistant for a project | 202 first-time / 200 idempotent. Body returns `BootstrapStateResponse`. |
| `DELETE` | `/workspace/{workspace_id}` | Disable assistant; cascade-delete data | 204 always (idempotent) |
| `GET` | `/workspace/{workspace_id}/status` | Poll bootstrap progress | 200 with `BootstrapStateResponse` / 404 |
| `DELETE` | `/users/{user_id}/chats` | Cascade-delete on ASOC user removal | 204 always (idempotent) |
| `GET` | `/health` | Liveness probe (no auth) | 200 with `{status: "ok"}` |

**Note on archive:** archive/unarchive endpoints were removed per grooming 2026-05. ASOC backend should call `DELETE /workspace/{id}` on project archive events; re-enabling requires calling `bootstrap` again.

#### `POST /api/v1/workspace/bootstrap`

```http
POST /api/v1/workspace/bootstrap HTTP/1.1
Authorization: Bearer <ASSISTANT_ASOC_TO_METRONIX_TOKEN>
Content-Type: application/json

{
  "workspace_id": "asoc-prod-12345678-abcd-...",
  "source": "asoc",
  "config": {
    "url": "https://asoc.example.com",
    "service_token": "<X-Api-Token of metatron system user>",
    "project_id": "12345678-abcd-...",
    "asoc_instance_id": "prod"
  }
}
```

`workspace_id` derivation: `f"asoc-{instance_id}-{project_id}"`. Must be unique per ASOC project across all ASOC instances served by this Metatron.

Response 202 Accepted (first-time):
```json
{
  "workspace_id": "asoc-prod-12345678-abcd-...",
  "state": "bootstrapping",
  "progress": 0.0,
  "current_step": null,
  "indexed_count": 0,
  "total_count": null,
  "last_synced_at": null,
  "last_error": null,
  "retry_count": 0,
  "next_retry_at": null,
  "updated_at": "2026-05-22T10:15:00Z"
}
```

For polling the progress, ASOC backend calls `GET /workspace/{id}/status` periodically (every 5-10 seconds during bootstrap). When `state == "ready"`, the UI may unlock the "Assistant" button.

If bootstrap fails (`state == "failed"`), Metatron's internal retry cron automatically schedules retries with exponential backoff (default base 60s, max 5 attempts). The UI should expose a "Retry" button for manual restart (also calls `POST /workspace/bootstrap` — idempotent on existing workspace_id).

#### `DELETE /api/v1/workspace/{workspace_id}`

Removes the workspace and all associated data: Qdrant collection, Neo4j namespace, PG rows (chat threads/messages, bootstrap_state, workspace metadata). Idempotent — returns 204 even if workspace doesn't exist.

#### `GET /api/v1/workspace/{workspace_id}/status`

Returns `BootstrapStateResponse`. 404 if workspace doesn't exist.

States:
- `bootstrapping` — initial indexing in progress
- `ready` — workspace is active; chat is available
- `failed` — bootstrap or sync failed; check `last_error`. Retry cron will re-attempt.

#### `DELETE /api/v1/users/{user_id}/chats`

Cascade-delete all chat threads + messages for a user across all workspaces. Called by ASOC when a user is deleted from ASOC. Idempotent (204 even for non-existent user).

### 2.2 Chat endpoints (chat channel — frontend direct)

ASOC frontend calls these **directly** (not proxied through ASOC backend). CORS is configured on Metatron via `METATRON_ASOC_ALLOWED_ORIGINS` — exact frontend domains to be provided by ASOC team.

Auth: the request carries the user's ASOC session_id in the `X-ASOC-Session: <session_id>` header (same header convention as ASOC's MCP server uses for delegated sessions). Metatron validates the session by calling ASOC's `session_ok` callback (see §3.1; pattern TBD) and caches the `session_id → user_id` mapping for `METATRON_ASOC_SESSION_CACHE_TTL_SECONDS` (default 3600).

| Method | Path | Purpose | Response |
|---|---|---|---|
| `POST` | `/asoc/chat` | Send a chat message; SSE stream back | 200 + SSE stream / 401 / 409 / 429 |
| `GET` | `/asoc/chat/threads` | List user's threads (one per workspace in MVP) | 200 with list / 401 |
| `GET` | `/asoc/chat/threads/{id}/messages` | History of a thread | 200 with messages / 401 / 404 |
| `DELETE` | `/asoc/chat/threads/{id}` | "New conversation" trigger | 204 / 401 / 404 |

#### `POST /api/v1/asoc/chat`

```http
POST /api/v1/asoc/chat HTTP/1.1
X-ASOC-Session: <user_session_id>
Content-Type: application/json
Accept: text/event-stream

{
  "message": "What critical SAST issues appeared this week?",
  "workspace_id": "asoc-prod-12345678-...",
  "history": null
}
```

Response 200 OK with `text/event-stream`. See §4 for event structure. Terminal SSE event is always `done`.

Failure cases (HTTP code returned before stream opens):
- 401 — session_id missing, invalid, or expired (session_ok callback returned non-200)
- 409 — workspace not ready (bootstrap not finished or in failed state); SSE error inside stream is `workspace_not_ready`
- 429 — per-user rate limit exhausted (`METATRON_CHAT_RATE_LIMIT_PER_MIN`, default 30 req/min)
- 503 — Metatron orchestrator not initialized (admin secret unset OR LLM endpoint unreachable)

Inside the stream, failures emit an `error` event then `done`. See §4.

#### `GET /api/v1/asoc/chat/threads`

```http
GET /api/v1/asoc/chat/threads?workspace_id=asoc-prod-... HTTP/1.1
X-ASOC-Session: <user_session_id>
```

Returns:
```json
{
  "threads": [
    {
      "thread_id": "...",
      "workspace_id": "asoc-prod-...",
      "user_id": "...",
      "created_at": "...",
      "last_message_at": "..."
    }
  ],
  "count": 1
}
```

MVP: returns 0 or 1 thread per (user, workspace). One thread per pair — confirmed (no multi-thread in MVP per grooming).

#### `GET /api/v1/asoc/chat/threads/{thread_id}/messages`

Returns ordered messages (oldest first). Hard cap of 1000 messages returned. UI uses this to render history when re-opening the chat panel.

#### `DELETE /api/v1/asoc/chat/threads/{thread_id}`

"New conversation" button in the UI maps to this. Deletes the thread (cascade to messages). Next chat message creates a new thread implicitly.

---

## 3. Metatron → ASOC — required endpoints

### 3.1 Session validation (`session_ok` — pattern TBD)

Metatron needs to validate the `session_id` that arrives from the ASOC frontend on `POST /api/v1/asoc/chat` and extract `user_id` from it. Decision pending — two viable options:

**Option A — Dedicated HTTP endpoint on ASOC backend** (new endpoint they ship):
```http
POST {ASOC_BASE_URL}/session_ok HTTP/1.1
Authorization: Bearer <ASSISTANT_ASOC_TO_METRONIX_TOKEN>
Content-Type: application/json

{"session_id": "..."}

→ 200 {"user_id": "...", "user_email": "...", "user_display_name": "..."}
→ 401/404 (invalid/expired)
```

**Option B — Use ASOC MCP `asoc_get_current_user` as the verification call** (no new endpoint):
- Metatron makes an MCP `tools/call` with `X-Api-Token: <admin_token>` + `X-ASOC-Session: <session_id>`
- ASOC's `withAuth` middleware validates the session (constant-time token check + `VerifySession`) and returns `asoc_get_current_user` response with `{id, username, display_name, email, roles, session_id}`
- Reuses existing mechanism — zero new code on ASOC side

Both options give Metatron `user_id` and validate the session. Option B is cheaper for ASOC; Option A is faster (single HTTP roundtrip vs MCP envelope). To be agreed.

Cache: in either case, Metatron caches `session_id → user_id` for `METATRON_ASOC_SESSION_CACHE_TTL_SECONDS` (default 3600) to avoid validating on every chat message.

Failure modes Metatron must handle either way:
- 401/404 / "session not found" → Metatron returns 401 to its own caller
- 5xx / timeout → Metatron retries with backoff; if persistent, returns 503

### 3.2 ASOC MCP server endpoints (used by Metatron)

Metatron acts as MCP client to ASOC's existing MCP server. **Two modes, one channel.** The same predefined `ASSISTANT_ASOC_TO_METRONIX_TOKEN` is used in both modes; the second header (`X-ASOC-Session`) distinguishes user-mode from admin-mode.

#### Admin mode (bootstrap + sync)

Used during initial bootstrap and periodic delta-sync. Acts as the predefined ASOC system user `metatron` (role `isadm`).

```http
POST {ASOC_MCP_URL}/mcp HTTP/1.1
X-Api-Token: <ASSISTANT_ASOC_TO_METRONIX_TOKEN>
Content-Type: application/json

{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "asoc_list_issues", "arguments": {...}}, "id": 1}
```

ASOC's `withAuth` middleware: no `X-ASOC-Session` header → falls to existing user-API-token path. Token matches `metatron` system user's token → context built as `metatron` (admin).

Tools used by Metatron for bootstrap + delta-sync (preliminary list):

| Tool | Purpose |
|---|---|
| `asoc_list_projects` | Project metadata |
| `asoc_list_layers` | Layer tree |
| `asoc_list_issues` | Issue list (paginated; `updated_after` filter requested for delta-sync efficiency) |
| `asoc_list_issue_comments` | Per-issue comments |
| `asoc_list_issue_history` | Per-issue status changes |
| `asoc_list_scans` | Scan results |
| `asoc_list_sboms` | SBOM listing per layer |
| `asoc_list_dependencies` | Dependencies |
| `asoc_list_gates` | Quality gate states |
| `asoc_list_events` | Project events |

Each tool's response items must include `updated_at`, `url_hint`, and parent ID where applicable (see ASOC plan §1.3 + §1.4).

#### User mode (chat tool-use + visibility filter)

Used when the chat LLM invokes a live tool, or when Metatron filters retrieved chunks through visibility filter. The user's session is forwarded so ASOC's RBAC applies automatically to the call.

```http
POST {ASOC_MCP_URL}/mcp HTTP/1.1
X-Api-Token: <ASSISTANT_ASOC_TO_METRONIX_TOKEN>
X-ASOC-Session: <user_session_id>
Content-Type: application/json

{"jsonrpc": "2.0", "method": "tools/call", "params": {...}, "id": 1}
```

ASOC's `withAuth` middleware: `X-ASOC-Session` present → token must match the `metatron` system token (constant-time compare) → `VerifySession(session_id)` resolves user → context built under user's RBAC.

User-mode tool whitelist: 37 read-only tools — full list in Metatron's `core/asoc_constants.py::ASOC_MCP_READ_ONLY_TOOLS_DEFAULT`. Configurable via `METATRON_ASOC_MCP_ALLOWED_TOOLS` env.

Write tools (15 of them: status changes, scan triggers, etc.) are **always blocked** in MVP. Double-gate enforcement: (1) filtered out at LLM tool-schema construction, (2) rejected pre-dispatch in `AsocMcpClient.invoke` if the LLM somehow emits a non-whitelisted name.

#### `asoc_visibility_filter` tool

Used by Metatron post-retrieval to filter chunks through ASOC's RBAC. Per ASOC plan §1.1.

Request (called in user mode):
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "asoc_visibility_filter",
    "arguments": {"resource_type": "issue", "ids": ["uuid1", "uuid2", "uuid3"]}
  },
  "id": 1
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "result": {"content": [{"type": "json", "data": {"ids": ["uuid1", "uuid3"]}}]},
  "id": 1
}
```

Supported `resource_type` values: `project`, `issue`, `scan`, `layer`, `gate` (exactly these 5).

⚠️ **Important: `scan` not `scan_result`; `gate` not `quality_gate`.** Metatron's chunk-to-resource_type grouping uses these canonical labels.

⚠️ **Response field is `ids`** (not `visible_ids`). Metatron parses accordingly.

⚠️ **`sbom` is not a supported `resource_type`.** Metatron groups sbom chunks via their parent `layer_id` (visibility checked against the parent layer, not the sbom itself).

Metatron groups chunks by resource_type and issues one tool call per group (parallel across types, sequential within), then merges. Hard-fail: any error → no LLM call, SSE `error: visibility_filter_failed`.

SLA: p95 < 1s, p99 < 5s (Metatron timeout: 5s configurable via `METATRON_ASOC_VISIBILITY_FILTER_TIMEOUT_SECONDS`).

### 3.3 ASOC product documentation ingestion

ASOC product docs (UI feature descriptions, how-to guides — anything that lets a user ask "what does this button do?") live in ASOC's database. They are ingested into every workspace at bootstrap time so users can ask about both project-specific data AND product functionality from the same chat.

**Ingestion mechanism:** ASOC pushes docs into Metatron via Metatron's existing document-ingestion HTTP endpoint. Pattern:

- During or after `POST /api/v1/workspace/bootstrap`, ASOC backend additionally calls Metatron's document ingestion endpoint with the doc payloads.
- Same docs ingested per workspace (cheap duplication — single-digit-MB per workspace).
- Existing endpoint: `POST /api/v1/documents` (see Metatron document API for shape).

**TBD with ASOC team:**
- Confirm Metatron's `/api/v1/documents` endpoint signature matches their needs, OR add a dedicated `POST /api/v1/workspace/{id}/docs` bulk-push endpoint
- Re-ingestion strategy: full replace per workspace? Or incremental?
- Trigger: at bootstrap time only, or also on ASOC release (new docs version → re-push to all workspaces)?

---

## 4. SSE event reference

The `POST /api/v1/asoc/chat` stream emits Server-Sent Events. Each event has an `event` and `data` line. JSON encoding for `data`.

| Event | Data payload | When |
|---|---|---|
| `status` | `{"status": "searching"\|"filtering"\|"answering"\|"tool_calling"}` | Phase indicator for UI |
| `chunk` | `{"text": "<incremental answer text>"}` | LLM token stream |
| `tool_call` | `{"tool": "asoc_count_issues", "status": "running"\|"done"\|"error", "reason": "<optional>"}` | Live MCP tool invocation during chat |
| `sources` | `{"sources": [{"anchor": "[1]", "source_type": "issue", "entity_id": "...", "display_id": "ASOC-1234", "title": "...", "url_hint": "/projects/.../issues/..."}]}` | Structured citations, emitted after LLM finishes if any citations exist |
| `done` | `{"workspace_id": "...", "thread_id": "..."}` | Always last event, every terminal path |
| `error` | `{"code": "<code>", "message": "..."}` | Failure inside the stream (before `done`) |

Error codes:
- `workspace_not_ready` — bootstrap not complete
- `visibility_filter_failed` — ASOC visibility filter raised; no LLM call happened
- `llm_unavailable` — LLM endpoint unreachable
- `timeout` — overall request budget exceeded (`METATRON_CHAT_TIMEOUT_SECONDS`, default 30s)

`rate_limited` is **NOT** an SSE error — Metatron returns HTTP 429 before opening the stream (per grooming).

### Example session (annotated)

```
event: status
data: {"status": "searching"}

event: status
data: {"status": "filtering"}

event: status
data: {"status": "answering"}

event: chunk
data: {"text": "On this week's scan, "}

event: chunk
data: {"text": "three critical issues were found "}

event: tool_call
data: {"tool": "asoc_count_issues", "status": "running"}

event: tool_call
data: {"tool": "asoc_count_issues", "status": "done"}

event: chunk
data: {"text": "with the following details:\n\n"}

event: chunk
data: {"text": "- Issue [1]: SQL injection in login flow\n"}

event: chunk
data: {"text": "- Issue [2]: ..."}

event: sources
data: {"sources": [
  {"anchor": "[1]", "source_type": "issue", "entity_id": "uuid-1", "display_id": "ASOC-1234", "title": "SQL injection in login flow", "url_hint": "/projects/p/issues/1234"},
  {"anchor": "[2]", "source_type": "issue", "entity_id": "uuid-2", "display_id": "ASOC-1235", "title": "...", "url_hint": "/projects/p/issues/1235"}
]}

event: done
data: {"workspace_id": "asoc-prod-...", "thread_id": "..."}
```

The frontend should render `chunk` events as incremental text, link `[N]` markers to the `sources` event (rendered as a clickable list under the answer), and update a phase indicator from `status` events.

---

## 5. Workspace lifecycle

```
                bootstrap()
                 │
                 ▼
          ┌──────────────┐
          │ bootstrapping│
          └──────┬───────┘
                 │
       ┌─────────┴─────────┐
       │                   │
   on success          on error
       │                   │
       ▼                   ▼
   ┌──────┐           ┌────────┐
   │ready │  ───────► │failed  │ ◄─── retry cron (auto) / manual bootstrap call
   └──┬───┘           └────┬───┘
      │                    │
      │   delete()         │  delete()
      │                    │
      ▼                    ▼
   ┌──────────────────────────┐
   │     absent (deleted)     │
   └──────────────────────────┘
```

ASOC actions trigger transitions:
- Enable assistant → `POST /api/v1/workspace/bootstrap` (absent → bootstrapping)
- Disable / archive event / project deleted → `DELETE /api/v1/workspace/{id}` (any → absent). Archive ≡ Delete per grooming.
- Polling progress → `GET /api/v1/workspace/{id}/status`
- Retry button → `POST /api/v1/workspace/bootstrap` again (idempotent)

Re-enable after a delete = full bootstrap from scratch (no archive/unarchive state to preserve).

---

## 6. Environment variables (Metatron side)

These are configured by the operator at deployment. ASOC team doesn't manage them, but should be aware of the configuration surface.

| Env var | Default | Purpose |
|---|---|---|
| `ASOC_BASE_URL` | (empty) | URL of ASOC backend (used for `session_ok` callback if Option A in §3.1) |
| `ASOC_MCP_URL` | (empty) | URL of ASOC MCP server |
| `ASOC_ADMIN_TOKEN` | (empty) | The predefined system-user token from ASOC (`ASSISTANT_ASOC_TO_METRONIX_TOKEN` on their side, same value). Used for: HTTP admin endpoints as `Authorization: Bearer`, MCP admin-mode as `X-Api-Token`, MCP user-mode as `X-Api-Token` (alongside `X-ASOC-Session`). |
| `METATRON_ASOC_INSTANCE_ID` | (empty) | ASOC instance identifier; used in `workspace_id = asoc-{instance}-{project_id}` |
| `METATRON_ASOC_ALLOWED_ORIGINS` | (empty) | CORS allow-list for ASOC frontend (CSV, e.g. `https://asoc.example.com`) |
| `METATRON_ASOC_SESSION_CACHE_TTL_SECONDS` | 3600 | TTL for session_id → user_id cache |
| `METATRON_ASOC_BOOTSTRAP_RETRY_MAX_ATTEMPTS` | 5 | Max retries on failed bootstrap |
| `METATRON_ASOC_BOOTSTRAP_RETRY_BACKOFF_BASE_SECONDS` | 60 | Backoff base for retry cron |
| `METATRON_ASOC_BOOTSTRAP_RETRY_INTERVAL_SECONDS` | 60 | Retry cron tick cadence |
| `METATRON_ASOC_SYNC_INTERVAL_SECONDS` | 900 | Delta sync cadence (15 min default) |
| `METATRON_ASOC_SYNC_MAX_CONCURRENT_WORKSPACES` | 3 | Semaphore on concurrent workspace syncs |
| `METATRON_ASOC_MCP_ALLOWED_TOOLS` | (37 read-only tools) | Whitelist for user-mode MCP tool-use |
| `METATRON_ASOC_VISIBILITY_FILTER_TIMEOUT_SECONDS` | 5 | Hard ceiling on visibility filter call |
| `METATRON_CHAT_API_BASE` | (empty) | LLM endpoint (OpenAI-compatible) |
| `METATRON_CHAT_API_KEY` | (empty) | LLM API key |
| `METATRON_CHAT_MODEL` | `gpt-4o-mini` | LLM model name |
| `METATRON_CHAT_RATE_LIMIT_PER_MIN` | 30 | Per-user rate limit on `POST /chat` |
| `METATRON_CHAT_TIMEOUT_SECONDS` | 30 | Per-request budget on `POST /chat` |
| `METATRON_CHAT_MAX_TOOL_CALLS_PER_REQUEST` | 8 | Cap on tool-use loop iterations |

**Counterpart env vars on ASOC side** (for reference, set by ASOC operator):
- `ASSISTANT_METRONIX_BASE_URL` = Metatron's URL
- `ASSISTANT_ASOC_TO_METRONIX_TOKEN` = same value as Metatron's `ASOC_ADMIN_TOKEN`

**Coordination required between ASOC and Metatron operators:**
- `ASOC_BASE_URL` + `ASOC_MCP_URL` — URLs of ASOC backend and MCP server
- `ASOC_ADMIN_TOKEN` — same string on both sides
- `METATRON_ASOC_INSTANCE_ID` — agreed identifier (`prod`, `staging`, etc.)
- `METATRON_ASOC_ALLOWED_ORIGINS` — ASOC frontend domain(s) — to be provided

---

## 7. Workspace_id derivation

`workspace_id = f"asoc-{ASOC_INSTANCE_ID}-{project_id}"`.

- `ASOC_INSTANCE_ID` = stable identifier of the ASOC installation (one per deployment).
- `project_id` = UUID of the ASOC project.

Example: `asoc-prod-12345678-abcd-...`

Both ASOC backend (when calling `POST /workspace/bootstrap`) and ASOC frontend (when calling `POST /chat`) must use this exact format. If they diverge, chat requests will hit a non-existent workspace and return 409 `workspace_not_ready`.

---

## 8. Operational notes

- Metatron is delivered as a standalone docker-compose stack (Metatron core + Postgres + Qdrant + Neo4j + optional TEI for embeddings). ASOC stack is unchanged.
- Connection between ASOC and Metatron: HTTP + MCP only. No shared databases, no shared filesystems.
- Bootstrap of a typical project (~10k issues + 100 scans + N comments) takes several minutes. The retry cron in Metatron is single-instance-safe (multi-replica deployments need a Redis lock — Phase 2).
- LLM is configured per Metatron deployment by the operator (env vars above). ASOC has no LLM configuration surface.
- Chat history is private per (user, project). Threads are NOT visible across projects or to other users.
- Read-only mode: the LLM cannot modify ASOC state via chat. All 15 write MCP tools (start_scan, set_status, etc.) are blocked at the tool whitelist level AND at the pre-dispatch check.

---

## 9. Resolutions and remaining open questions

This section tracks what's been confirmed via grooming sessions and ASOC's implementation plan (Confluence 75169793), and what still needs alignment before Metatron can finish the rework.

### ✅ Confirmed

1. **Session ID transport** — header `X-ASOC-Session: <session_id>`. Same convention as ASOC's MCP middleware uses for delegated sessions.
2. **Cookie vs header for chat auth** — header-only. ASOC frontend reads `session_id` from its own state (localStorage / sessionStorage / wherever) and sends it in `X-ASOC-Session`. No HTTP-only cookie path. Metatron does NOT set `Access-Control-Allow-Credentials: true` — simpler CORS.
3. **Admin token transport** — HTTP direction: `Authorization: Bearer <ASSISTANT_ASOC_TO_METRONIX_TOKEN>`. MCP direction: `X-Api-Token: <ASSISTANT_ASOC_TO_METRONIX_TOKEN>`. Same value across both, different headers per ASOC's MCP `withAuth` middleware convention.
4. **MCP admin tool access** — Metatron's calls authenticate as predefined ASOC system user `metatron` with role `isadm`. Tool list is the same 37 read-only tools as user-mode (the role just removes per-project RBAC restrictions).
5. **`asoc_visibility_filter` MCP tool** — confirmed. Input `{resource_type: project|issue|scan|layer|gate, ids: []string}`. Output `{ids: []string}`. `sbom` not supported as a resource_type (sbom chunks group under `layer` via parent_id). Note: response field is `ids` (not `visible_ids`), and `scan`/`gate` are canonical (not `scan_result`/`quality_gate`).
6. **URL retrieval for citations** — each entity in MCP tool responses includes `url_hint` field. Metatron passes this through into the `sources` SSE event, no template-based URL construction on Metatron side. Templates are configured per-entity on ASOC side via `EntityURLTemplates` config + `AppInfo.ASOCFront` base (their plan §1.4).
7. **Archive=Delete** — `archive`/`unarchive` endpoints removed on Metatron side (already done). ASOC backend calls `DELETE /workspace/{id}` on project archive events.
8. **Threads count** — one thread per (user, project) for MVP. `DELETE /api/v1/asoc/chat/threads/{id}` is the "New conversation" trigger. Next chat message implicitly creates a new thread.
9. **Tool rename** — `asoc_get_profile` → `asoc_get_current_user` (already done on ASOC side). Metatron's whitelist updated accordingly.
10. **Endpoint paths** — Metatron keeps current paths (`/api/v1/workspace/bootstrap`, `/api/v1/workspace/{workspace_id}`, etc.). ASOC adapter calls them as documented in §2.
11. **`session_ok` pattern** — Option B confirmed: Metatron uses existing `asoc_get_current_user` MCP tool to validate session + extract user identity in one call (sending `X-Api-Token` + `X-ASOC-Session`; ASOC's `withAuth` middleware validates the session as a side effect, returns 401 if invalid, returns user payload if valid). No new endpoint needed on ASOC side.
12. **CORS origins** — env-driven on Metatron side (`METATRON_ASOC_ALLOWED_ORIGINS`); customer-operator fills in their ASOC frontend domain(s) at install time. Default empty (CORS disabled). Already implemented.
13. **`asoc_list_*` filter parameter for delta-sync** — agreed in principle by ASOC team. Exact param name TBD (`updated_after` or analog). Metatron's T1 implementation will code against an assumed name, easily aliased once confirmed; until then, fallback to full-pull + content-hash dedup at ingestion works correctly (just wasteful at large project scale).
14. **`url_hint` field scope** — only on entity-returning tools (`asoc_list_*`, `asoc_get_*`). Aggregation/stats tools (`asoc_visibility_filter`, `asoc_count_issues`, `asoc_get_stats_*`) don't include `url_hint`. Per ASOC plan §1.4: "Сервисы без url_hint: StatsService, CopilotService".

### ❓ Remaining open (non-blocking)

1. **Docs ingestion mechanism** — agreed in principle that ASOC pushes product docs to Metatron via existing document-ingestion HTTP endpoint. Pending finalization: shape of payload (which Metatron endpoint exactly), trigger (at bootstrap-only or also on ASOC release), re-ingestion strategy (full replace per workspace). Sergey owns the proposal on ASOC side. **Does NOT block T1/T4/T5/T6 rework** — separate workstream.

---

## 10. Status checklist (Metatron side)

### Already implemented

- [x] Workspace bootstrap + state machine + retry cron
- [x] Periodic delta sync cron skeleton (depends on T1 MCP rework to actually fetch)
- [x] Chat orchestrator pipeline (retrieval + LLM streaming)
- [x] Persistent chat history (Postgres-backed, single thread per pair)
- [x] User cascade delete endpoint (`DELETE /api/v1/users/{user_id}/chats`)
- [x] MCP client (user-mode) with 37-tool whitelist + double-gate write blocking
- [x] MCP client (admin-mode skeleton — class accepts admin_token + mode kwarg)
- [x] CORS middleware infrastructure (env-driven; origins still to be configured)
- [x] Rate limit on chat returns HTTP 429 (not SSE in-band)
- [x] LLM streaming with `cite_source` function-calling for structured citations
- [x] SSE event protocol per §4
- [x] Archive/unarchive endpoints removed (Archive=Delete)
- [x] `gate` canonical entity_type (with `quality_gate` defensive alias)

### Ready to start — newly unblocked by ASOC implementation plan

- [ ] Replace HS256 JWT auth on `POST /api/v1/asoc/chat` with `X-ASOC-Session` + cache + session validation (Option A or B from §3.1 — pick one)
- [ ] Replace `require_admin` on workspace lifecycle endpoints with `Authorization: Bearer <ASOC_ADMIN_TOKEN>` check
- [ ] T6 user-mode MCP client: switch from `Authorization: Bearer <user_jwt>` to `X-Api-Token: <admin_token>` + `X-ASOC-Session: <session_id>`
- [ ] T6 admin-mode MCP client: use `X-Api-Token` header (not `Authorization: Bearer`)
- [ ] T1 AsocConnector: rewrite REST → MCP tool calls (admin-mode)
- [ ] T5 AsocVisibilityFilter: change `resource_type=scan_result` → `scan`, response field `visible_ids` → `ids`, ensure sbom never goes as standalone resource_type
- [ ] Whitelist update: rename `asoc_get_profile` → `asoc_get_current_user` in `core/asoc_constants.py`
- [ ] T1 remove `_URL_HINT_BUILDERS` — read `url_hint` from MCP responses instead

### Parallel workstream (does not block our rework)

- [ ] Docs ingestion mechanism finalized with ASOC (Sergey owns) — once the payload shape is agreed, Metatron exposes an ingestion endpoint (likely reusing existing `/api/v1/documents` or adding bulk variant)

---

## References

- Internal Jira: MTRNIX-340 (epic), MTRNIX-370 (rework, in progress)
- Original Confluence concept (Metatron side): https://mtrnix.atlassian.net/wiki/spaces/MTRNIX/pages/33783809
- ASOC implementation plan: Confluence 75169793 (ASOC team, MCP enhancements + Metronix HTTP adapter)
- Pull request: https://github.com/mtrnix/metatroncore/pull/122
