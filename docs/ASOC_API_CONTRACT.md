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

| Direction | Transport | Auth | Purpose |
|---|---|---|---|
| ASOC backend → Metatron | HTTP | static shared secret | Workspace lifecycle (bootstrap / delete / status), user cascade |
| ASOC frontend → Metatron | HTTP + SSE | `session_id` exchange | Chat orchestration (POST /chat), thread management |
| Metatron → ASOC | MCP (admin mode) | static admin token | Initial bootstrap + periodic delta sync of project entities |
| Metatron → ASOC | MCP (user mode) | user session | Live tool-calls during chat, visibility filtering |
| Metatron → ASOC | HTTP | (none / admin secret) | Single `session_ok` callback to exchange session_id for user_id |

**No JWT.** Earlier design used HS256 JWTs; revised approach uses static shared secrets and ASOC session_id directly. Simpler operationally.

---

## 2. ASOC → Metatron — HTTP endpoints

All endpoints prefixed `/api/v1/`. Metatron's base URL is configured on the ASOC backend (e.g. `METATRON_URL=http://metatron:8000`).

### 2.1 Admin endpoints (admin channel)

Auth: every request includes `X-ASOC-Admin-Secret: <secret>` header. The secret is identical on both sides (env var on ASOC backend and Metatron). 401 on missing/wrong header. 503 if Metatron's `ASOC_ADMIN_SECRET` env is empty (operator misconfig).

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
Authorization: ... (admin secret per chosen header convention)
Content-Type: application/json

{
  "workspace_id": "asoc-prod-12345678-abcd-...",
  "source": "asoc",
  "config": {
    "url": "https://asoc.example.com",
    "service_token": "<X-API-Token of Metronix_sync role>",
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

ASOC frontend calls these **directly** (not proxied through ASOC backend). CORS is configured on Metatron via `METATRON_ASOC_ALLOWED_ORIGINS`.

Auth: the request carries the user's ASOC session_id (transport TBD — see §9 open questions). Metatron exchanges session_id → user_id via `session_ok` callback (see §3) on cache-miss, then caches the mapping with configurable TTL.

| Method | Path | Purpose | Response |
|---|---|---|---|
| `POST` | `/asoc/chat` | Send a chat message; SSE stream back | 200 + SSE stream / 401 / 409 / 429 |
| `GET` | `/asoc/chat/threads` | List user's threads (one per workspace in MVP) | 200 with list / 401 |
| `GET` | `/asoc/chat/threads/{id}/messages` | History of a thread | 200 with messages / 401 / 404 |
| `DELETE` | `/asoc/chat/threads/{id}` | "New conversation" trigger | 204 / 401 / 404 |

#### `POST /api/v1/asoc/chat`

```http
POST /api/v1/asoc/chat HTTP/1.1
Cookie: session_id=...   (or via header — TBD)
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
Cookie: session_id=...
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

MVP: returns 0 or 1 thread per (user, workspace). Multi-thread is open — see §9.

#### `GET /api/v1/asoc/chat/threads/{thread_id}/messages`

Returns ordered messages (oldest first). Hard cap of 1000 messages returned. UI uses this to render history when re-opening the chat panel.

#### `DELETE /api/v1/asoc/chat/threads/{thread_id}`

"New conversation" button in the UI maps to this. Deletes the thread (cascade to messages). Next chat message creates a new thread implicitly.

---

## 3. Metatron → ASOC — required endpoints

### 3.1 `POST /session_ok` (new ASOC endpoint)

Metatron calls this to exchange a session_id for a user_id. Cached on Metatron side with TTL (`METATRON_ASOC_SESSION_CACHE_TTL_SECONDS`, default 3600).

Expected contract (TBD — finalize with ASOC, see §9 open questions):
```http
POST {ASOC_BASE_URL}/session_ok HTTP/1.1
X-ASOC-Admin-Secret: <secret>     (or other admin auth — TBD)
Content-Type: application/json

{"session_id": "..."}
```

Expected response 200:
```json
{
  "user_id": "...",
  "user_email": "...",
  "user_display_name": "...",
  "project_ids_accessible": ["...", "..."]
}
```

Failure modes Metatron must handle:
- 401/404 — session invalid/expired → Metatron returns 401 to its own caller
- 5xx / timeout — Metatron retries with backoff; if persistent, returns 503

### 3.2 ASOC MCP server endpoints (used by Metatron)

Metatron acts as MCP client to ASOC's existing MCP server. **Two modes, one channel:**

#### Admin mode

Used during bootstrap and periodic delta-sync. Single static admin token, broad read access.

```http
POST {ASOC_MCP_URL}/mcp HTTP/1.1
Authorization: Bearer <admin_token>
Content-Type: application/json

{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "asoc_list_issues", "arguments": {...}}, "id": 1}
```

Tools used (preliminary list — confirm with ASOC, see §9):

| Tool | Purpose |
|---|---|
| `asoc_list_projects` | Project metadata |
| `asoc_list_layers` | Layer tree |
| `asoc_list_issues` | Issue list (with `updated_after` filter) |
| `asoc_list_issue_comments` | Per-issue comments |
| `asoc_list_issue_history` | Per-issue status changes |
| `asoc_list_scans` | Scan results |
| `asoc_list_sboms` | SBOM listing per layer |
| `asoc_list_dependencies` | Dependencies |
| `asoc_list_quality_gates` | Quality gate states |
| `asoc_list_events` | Project events |

Each tool must support pagination and `updated_after` filter (for delta-sync).

#### User mode

Used during chat tool-use loop — when the LLM invokes a tool inside a chat response. The user's session is forwarded so ASOC RBAC applies automatically.

```http
POST {ASOC_MCP_URL}/mcp HTTP/1.1
Authorization: Bearer <user_session_token>   (TBD — same session_id or a derived bearer?)
Content-Type: application/json

{"jsonrpc": "2.0", "method": "tools/call", "params": {...}, "id": 1}
```

User-mode whitelist (37 read-only tools, currently configured via `METATRON_ASOC_MCP_ALLOWED_TOOLS` — full list in Metatron's `core/asoc_constants.py::ASOC_MCP_READ_ONLY_TOOLS_DEFAULT`).

Write tools are **always blocked** in MVP (HITL + prompt-injection audit required first).

#### `asoc_visibility_filter` tool (new — required from ASOC)

Used by Metatron to filter retrieved chunks before sending them to the LLM. Replaces the previously-discussed REST endpoint per grooming.

Expected shape (confirm with ASOC):
```json
{"jsonrpc": "2.0", "method": "tools/call",
 "params": {"name": "asoc_visibility_filter",
            "arguments": {"resource_type": "issue", "ids": ["uuid1", "uuid2"]}},
 "id": 1}
```

Response:
```json
{"jsonrpc": "2.0", "result": {"content": [{"type": "json", "data": {"visible_ids": ["uuid1"]}}]}, "id": 1}
```

`resource_type` accepts: `issue`, `scan_result`, `layer`, `project`. Metatron groups chunks by resource_type and issues one tool call per group, then merges. Hard-fail: any error → no LLM call, SSE `error: visibility_filter_failed`.

SLA: p95 < 1s, p99 < 5s (Metatron timeout: 5s configurable).

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
- Enable assistant → `POST /workspace/bootstrap` (absent → bootstrapping)
- Disable / archive / project deleted → `DELETE /workspace/{id}` (any → absent)
- Polling progress → `GET /workspace/{id}/status`
- Retry button → `POST /workspace/bootstrap` again (idempotent)

Note: `archive/unarchive` removed per grooming. Re-enable = full bootstrap.

---

## 6. Environment variables (Metatron side)

These are configured by the operator at deployment. ASOC team doesn't manage them, but should be aware of the configuration surface.

| Env var | Default | Purpose |
|---|---|---|
| `ASOC_BASE_URL` | (empty) | URL of ASOC backend for callbacks (visibility filter pre-MCP, session_ok) |
| `ASOC_MCP_URL` | (empty) | URL of ASOC MCP server |
| `ASOC_ADMIN_SECRET` | (empty) | Shared secret for admin channel HTTP auth (header convention TBD) |
| `ASOC_MCP_ADMIN_TOKEN` | (empty) | Static admin token for admin-mode MCP calls (bootstrap, sync) |
| `METATRON_ASOC_INSTANCE_ID` | (empty) | ASOC instance identifier; used in `workspace_id = asoc-{instance}-{project}` |
| `METATRON_ASOC_ALLOWED_ORIGINS` | (empty) | CORS allow-list for ASOC frontend (CSV) |
| `METATRON_ASOC_SESSION_CHECK_URL` | (empty) | URL of ASOC `session_ok` endpoint (e.g. `{ASOC_BASE_URL}/session_ok`) |
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

ASOC team needs to coordinate values for: `ASOC_BASE_URL`, `ASOC_MCP_URL`, `ASOC_ADMIN_SECRET`, `ASOC_MCP_ADMIN_TOKEN`, `METATRON_ASOC_INSTANCE_ID`, `METATRON_ASOC_ALLOWED_ORIGINS`, `METATRON_ASOC_SESSION_CHECK_URL`.

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

## 9. Open questions to confirm with ASOC

Numbered for cross-reference with internal Jira (MTRNIX-370):

1. **Session ID transport.** Where does ASOC place the session_id when calling `POST /api/v1/asoc/chat`? Cookie (`Cookie: session_id=...`)? Authorization header (`Authorization: Session ...`)? Custom header (`X-ASOC-Session: ...`)? Exact key name?

2. **`session_ok` endpoint contract.** Confirm the path, request body shape, response payload, and behavior on invalid sessions (401 vs 404). Recommended cache TTL? Does the session_id rotate (i.e. can Metatron's cache go stale even before TTL)?

3. **Admin shared secret transport.** What HTTP header convention should Metatron use to send the admin secret on workspace lifecycle endpoints? `Authorization: Bearer <secret>` / `X-ASOC-Admin-Secret: <secret>` / something else? One secret for everything, or distinct secrets for HTTP admin channel vs MCP admin channel?

4. **MCP admin tool inventory.** What tools does ASOC's MCP server expose to admin-mode callers (Metatron sync)? Are the 10 list-style tools enumerated in §3.2 sufficient? Are there additional admin-only tools (e.g. for backfill / re-indexing)?

5. **Product documentation source.** Per grooming, the bootstrap step should ingest ASOC product documentation into every workspace (so the assistant can answer "what does this UI button do?" alongside project-specific questions). Where is this documentation maintained — Confluence space, Markdown files in a repo, scraped from the ASOC UI? What's the canonical fetch path? (Sergey to propose.)

6. **Threads count.** Per grooming, the analytics doc suggests multiple chat threads per (user, project) with a switcher in the UI, but the demo showed only one. Confirm the MVP target: one thread per pair, or multiple? Affects the `chat_threads` table schema.

7. **`asoc_visibility_filter` MCP tool exact name + shape.** Confirm tool name. Confirm request `{resource_type, ids}` and response `{visible_ids}`. Is `resource_type` an enum of exactly `[issue, scan_result, layer, project]` or are more values needed?

8. **CORS origins.** What ASOC frontend domains should Metatron allow in CORS? Production + staging?

9. **URL retrieval for citations.** When the LLM emits a `cite_source` call, the `url_hint` field needs to point to the ASOC UI for that entity. Two options: (a) Metatron stores the URL template at ingest time and substitutes IDs at retrieval; (b) Each MCP tool response includes the URL alongside the entity payload, and the connector picks it up. Which does ASOC prefer?

10. **Archive removal confirmation.** Confirm that ASOC backend code that handles project archive events will call `DELETE /workspace/{id}` (instead of the removed `/archive` endpoint). On unarchive, full bootstrap restart is acceptable (re-index from scratch).

---

## 10. Status checklist (Metatron side)

What's already implemented and ready for ASOC integration testing:

- [x] Workspace bootstrap + state machine
- [x] Retry cron with exponential backoff
- [x] Periodic delta sync cron (depends on AsocConnector — see below)
- [x] Chat orchestrator pipeline (retrieval + LLM streaming)
- [x] Persistent chat history (Postgres-backed)
- [x] User cascade delete endpoint
- [x] MCP client (user mode, 37-tool whitelist, double-gate write blocking)
- [x] MCP client (admin mode skeleton — needs T1 rewrite to activate)
- [x] CORS middleware (env-configurable)
- [x] Rate limit on chat (HTTP 429)
- [x] LLM streaming with `cite_source` function-calling
- [x] SSE event protocol per §4

Blocked on ASOC answers above:

- [ ] Session-based auth on `POST /chat` (currently still has HS256 JWT verifier from earlier design — pending §9.1, §9.2)
- [ ] Admin-secret auth on workspace endpoints (currently uses Metatron internal admin JWT — pending §9.3)
- [ ] AsocConnector via MCP (currently REST-based — pending §9.4)
- [ ] AsocVisibilityFilter via MCP (currently REST-based — pending §9.7)
- [ ] ASOC product docs ingestion at bootstrap (pending §9.5)
- [ ] CORS origins configured (pending §9.8)
- [ ] URL retrieval contract (pending §9.9)

---

## References

- Internal Jira: MTRNIX-340 (epic), MTRNIX-370 (rework, in progress)
- Original Confluence concept: https://mtrnix.atlassian.net/wiki/spaces/MTRNIX/pages/33783809
- Pull request: https://github.com/mtrnix/metatroncore/pull/122
