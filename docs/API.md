# Metronix Core — REST API Reference

Base URL: `http://localhost:8000`

Interactive OpenAPI schema (when the server is running): `http://localhost:8000/docs`

For **MCP tools** (recommended for agent runtimes), see [`docs/MCP_API.md`](MCP_API.md).

---

## Authentication

When `METRONIX_AUTH_ENABLED=true` (production default), pass a JWT or personal API key:

```bash
export TOKEN="eyJ..."
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/auth/me
```

| Mechanism | Header | Notes |
|---|---|---|
| JWT (login) | `Authorization: Bearer <jwt>` | From `POST /api/v1/auth/login` |
| Personal API key | `Authorization: Bearer mtk_...` | Created via `/api/v1/users/{id}/api-keys` |
| OpenAI-compat key | `Authorization: Bearer mtk_...` or static `METRONIX_OPENAI_COMPAT_KEY` | `/v1/*` endpoints only |
| MCP | `Authorization: Bearer <METRONIX_MCP_API_KEY>` | `/mcp` (see MCP doc) |

**RBAC hierarchy:** `viewer` < `editor` < `admin`. Endpoints below note the minimum role when auth is enabled.

---

## Workspace scoping

| Pattern | Endpoints | How workspace is resolved |
|---|---|---|
| Auth-derived | `/api/v1/memory/*`, `/api/v1/knowledge/*`, `/api/v1/agents/*`, `/api/v1/snapshots/*`, `/api/v1/files/*`, `/api/v1/upload` | JWT claim `workspace_ids[0]`, unless `?workspace_id=` is passed **and** the token grants access (`*` or membership) → else 403 |
| Query / body | `/api/v1/connections/*`, `/api/v1/dashboard/*`, legacy `/api/v1/chat` | `?workspace_id=` or request body field |
| OpenAI-compat | `/v1/chat/completions` | Encoded in model name: `metronix-rag-{workspace_id}` |

Admin tokens with `workspace_ids: ["*"]` may target any workspace via `?workspace_id=`.

---

## Endpoint index

| Method | Path | Role | Description |
|---|---|---|---|
| **Health** |
| GET | `/health` | — | Liveness |
| GET | `/ready` | — | Readiness (Qdrant, Neo4j, Ollama) |
| GET | `/metrics` | — | App metrics |
| POST | `/metrics/reset` | — | Reset metrics |
| **Auth** |
| POST | `/api/v1/auth/login` | — | Email+password → JWT |
| GET | `/api/v1/auth/me` | — | Current user from JWT |
| GET | `/api/v1/config` | — | Installed plugins |
| **Chat (legacy UI)** |
| POST | `/api/v1/chat` | — | RAG Q&A (non-stream) |
| POST | `/api/v1/chat/stream` | — | RAG Q&A (SSE) |
| POST | `/api/v1/upload` | editor | Legacy single-file upload alias |
| **Files / upload pipeline** |
| POST | `/api/v1/files/` | editor | Multipart upload (1..N files) |
| POST | `/api/v1/files/import-path` | admin | Server-side folder import |
| **Workspaces** |
| GET | `/api/v1/workspaces/` | — | List workspaces |
| POST | `/api/v1/workspaces/` | — | Create workspace |
| GET | `/api/v1/workspaces/{id}` | — | Get workspace |
| DELETE | `/api/v1/workspaces/{id}` | — | Delete workspace + data |
| POST | `/api/v1/workspaces/{id}/activate` | — | Set active workspace for user |
| GET | `/api/v1/workspaces/{id}/stats` | — | Workspace statistics |
| **Connections** |
| GET | `/api/v1/connections/schemas/` | — | Connector form schemas |
| POST | `/api/v1/connections/` | — | Create connection |
| GET | `/api/v1/connections/` | — | List connections |
| GET | `/api/v1/connections/{id}/` | — | Get connection (masked secrets) |
| GET | `/api/v1/connections/{id}/reveal-secrets/` | editor | Get connection (decrypted secrets) |
| PUT | `/api/v1/connections/{id}/` | — | Update connection |
| DELETE | `/api/v1/connections/{id}/` | — | Delete connection |
| POST | `/api/v1/connections/{id}/test/` | — | Test connector config |
| POST | `/api/v1/connections/{id}/sync/` | — | Trigger manual sync |
| **Sync** |
| GET | `/api/v1/sync/status` | — | Sync status (stub) |
| GET | `/api/v1/sync/logs` | — | Sync logs (stub) |
| **Documents** |
| GET | `/api/v1/documents/{id}/history` | — | Document version history |
| **Graph (visualization)** |
| GET | `/api/v1/graph/overview` | — | Top connected entities |
| GET | `/api/v1/graph/expand/{entity_id}` | — | Expand entity neighbourhood |
| **Memory** |
| POST | `/api/v1/memory/records` | editor | Create memory record |
| POST | `/api/v1/memory/search` | viewer | Hybrid memory search |
| GET | `/api/v1/memory/records` | viewer | List memory records |
| GET | `/api/v1/memory/records/{id}` | viewer | Get single record |
| DELETE | `/api/v1/memory/records/{id}` | editor | Delete record |
| GET | `/api/v1/memory/graph` | viewer | Memory neighbourhood graph |
| GET | `/api/v1/memory/review` | viewer | Freshness review queue |
| POST | `/api/v1/memory/review/{id}` | editor | Resolve review entry |
| **Knowledge (unified inspector view)** |
| GET | `/api/v1/knowledge/records` | viewer | Agent memory + KB documents |
| **Agents** |
| POST | `/api/v1/agents/` | editor | Create agent |
| GET | `/api/v1/agents/` | viewer | List agents |
| GET | `/api/v1/agents/{id}` | viewer | Get agent |
| PUT | `/api/v1/agents/{id}` | editor | Update agent config |
| DELETE | `/api/v1/agents/{id}` | editor | Soft-delete (archived) |
| POST | `/api/v1/agents/{id}/start` | editor | Lifecycle → active |
| POST | `/api/v1/agents/{id}/stop` | editor | Lifecycle → stopped |
| POST | `/api/v1/agents/{id}/pause` | editor | Lifecycle → paused |
| POST | `/api/v1/agents/{id}/restore` | editor | archived → stopped |
| POST | `/api/v1/agents/{id}/reset` | editor | Wipe agent memory (+ auto snapshot) |
| POST | `/api/v1/agents/{id}/snapshots` | editor | Manual memory snapshot |
| GET | `/api/v1/agents/{id}/snapshots` | viewer | List snapshots |
| GET | `/api/v1/agents/{id}/versions` | viewer | Config version history |
| GET | `/api/v1/agents/{id}/memory/health` | viewer | Memory health metrics |
| GET | `/api/v1/agents/{id}/activity` | viewer | Activity timeline |
| GET | `/api/v1/agents/{id}/activity/summary` | viewer | Activity aggregates |
| **Snapshots** |
| POST | `/api/v1/snapshots/{id}/restore` | editor | Restore snapshot |
| GET | `/api/v1/snapshots/diff` | viewer | Diff two snapshots |
| GET | `/api/v1/snapshots/{id}/records` | viewer | Fetch records from snapshot file |
| **Traces** |
| GET | `/api/v1/traces/` | viewer | List RAG debug traces |
| GET | `/api/v1/traces/{trace_id}` | viewer | Full trace JSONB |
| **Dashboard** |
| GET | `/api/v1/dashboard/overview` | — | KPI overview |
| GET | `/api/v1/dashboard/query-trend` | — | Query volume trend |
| GET | `/api/v1/dashboard/sync-history` | — | Recent sync history |
| GET | `/api/v1/dashboard/ingestion-errors` | — | Ingestion errors |
| GET | `/api/v1/dashboard/graph-stats` | — | Graph statistics |
| **Admin** |
| GET | `/api/v1/admin/status` | — | System status |
| GET | `/api/v1/admin/cleanup/preview` | — | Cleanup preview |
| DELETE | `/api/v1/admin/cleanup/workspace/{id}` | — | Delete workspace data |
| DELETE | `/api/v1/admin/cleanup/all` | — | Delete all data |
| POST | `/api/v1/admin/reindex` | — | Global reindex trigger |
| POST | `/api/v1/admin/import-openwebui-users` | admin | Import OWUI users |
| **Users** |
| POST | `/api/v1/users` | admin | Create user |
| GET | `/api/v1/users` | admin | List users |
| GET | `/api/v1/users/{id}` | admin | Get user |
| PATCH | `/api/v1/users/{id}` | admin | Update user |
| DELETE | `/api/v1/users/{id}` | admin | Delete user |
| POST | `/api/v1/users/{id}/api-keys` | admin | Create API key |
| GET | `/api/v1/users/{id}/api-keys` | admin | List API keys |
| DELETE | `/api/v1/users/{id}/api-keys/{prefix}` | admin | Revoke API key |
| **Skills (legacy / inactive engine)** |
| GET/POST | `/api/v1/skills/` | — | CRUD |
| GET/PUT/DELETE | `/api/v1/skills/{id}` | — | CRUD |
| **FinOps** |
| GET | `/api/v1/finops/time-savings` | — | Time savings metrics |
| GET | `/api/v1/finops/active-users` | — | Active user counts |
| GET | `/api/v1/finops/cost-savings` | — | Cost savings metrics |
| **Benchmarker** |
| POST | `/api/v1/query/trace` | — | Single query trace |
| POST | `/api/v1/benchmarker/generate` | — | Generate benchmark questions |
| POST | `/api/v1/benchmarker/run-tests` | — | Run benchmark |
| GET/POST/DELETE | `/api/v1/benchmarker/benchmarks/*` | — | Benchmark sets |
| GET/POST/DELETE | `/api/v1/benchmarker/test-runs/*` | — | Test runs |
| **OpenAI-compatible** |
| GET | `/v1/models` | key | List models |
| GET | `/v1/openapi.json` | — | Connection stub |
| POST | `/v1/chat/completions` | key | RAG-backed chat |
| POST | `/v1/proxy/chat/completions` | key | LLM proxy (when enabled) |

---

## Health

### GET /health

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### GET /ready

Probes Qdrant, Neo4j, Ollama. Returns `200` with `"status": "ready"` or `"degraded"`.

```bash
curl http://localhost:8000/ready
```

### GET /metrics · POST /metrics/reset

```bash
curl http://localhost:8000/metrics
curl -X POST http://localhost:8000/metrics/reset
```

---

## Auth

### POST /api/v1/auth/login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your-password"}'
```

Response:

```json
{
  "token": "eyJ...",
  "user_id": "uuid",
  "email": "admin@example.com",
  "display_name": "Admin",
  "role": "admin"
}
```

Legacy fallback (no email, shared password only): `{"password":"..."}` → admin token.

### GET /api/v1/auth/me

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/auth/me
```

---

## Config

### GET /api/v1/config

Public. Returns installed plugin names (used by UI to detect enterprise features).

```bash
curl http://localhost:8000/api/v1/config
# {"plugins": ["enterprise"]}
```

---

## Files & upload pipeline

Upload endpoints parse file bytes to text and ingest through the **same connector pipeline** as Confluence/Jira sync:

```
parse → raw_documents (PostgreSQL, sync) → Qdrant + Neo4j (background)
```

Original binaries are **not** stored on disk. There is no download URL.

**Allowed extensions:** `.pdf`, `.docx`, `.xlsx`, `.csv`, `.html`, `.htm`, `.txt`, `.md`

**Per-file result statuses:** `accepted` · `skipped_format` · `skipped_empty` · `failed`

**HTTP status:** `200` when all files accepted · `207 Multi-Status` when any file skipped/failed

### POST /api/v1/files/ — multipart upload

**Role:** editor · **Workspace:** JWT or `?workspace_id=`

Multipart field name: `files` (repeat for multiple files).

```bash
curl -X POST "http://localhost:8000/api/v1/files/?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@report.pdf" \
  -F "files=@notes.md"
```

Response:

```json
{
  "workspace_id": "default",
  "accepted": 2,
  "skipped": 0,
  "results": [
    {"filename": "report.pdf", "status": "accepted", "source_id": "report.pdf", "reason": null},
    {"filename": "notes.md", "status": "accepted", "source_id": "notes.md", "reason": null}
  ]
}
```

Partial failure example (unsupported `.zip` + empty file → `207`):

```json
{
  "workspace_id": "default",
  "accepted": 1,
  "skipped": 2,
  "results": [
    {"filename": "ok.txt", "status": "accepted", "source_id": "ok.txt", "reason": null},
    {"filename": "bad.zip", "status": "skipped_format", "source_id": null, "reason": "extension zip not allowed"},
    {"filename": "empty.txt", "status": "skipped_empty", "source_id": null, "reason": "no extractable text"}
  ]
}
```

### POST /api/v1/files/import-path — server-side folder import

**Role:** admin · Reads files from a path **on the Metronix server filesystem**.

```bash
curl -X POST "http://localhost:8000/api/v1/files/import-path?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"path": "/data/import/docs", "recursive": true}'
```

Same response shape as multipart upload.

### POST /api/v1/upload — legacy alias

**Role:** editor · Backward-compatible single-file endpoint. Delegates to the same `_ingest_uploads` pipeline as `/api/v1/files/`.

Differences from the old behaviour:
- No on-disk file persistence
- No download URL in response
- `extract_graph` form field is ignored (graph extraction always runs in background)
- Workspace comes only from JWT / access-checked `?workspace_id=` (form fields cannot override)

Multipart field name: `file` (singular).

```bash
curl -X POST "http://localhost:8000/api/v1/upload?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.pdf"
```

Response (same schema as `/api/v1/files/`):

```json
{
  "workspace_id": "default",
  "accepted": 1,
  "skipped": 0,
  "results": [
    {"filename": "document.pdf", "status": "accepted", "source_id": "document.pdf", "reason": null}
  ]
}
```

> **Removed endpoints** (pre-connector-pipeline): `GET /api/v1/files`, `GET /api/v1/files/{id}/verify`, `GET /api/v1/files/{id}/download`.

---

## Chat (legacy REST UI)

Built-in chat endpoints for OpenWebUI-era integrations. New agent integrations should prefer MCP or `/v1/chat/completions`.

### POST /api/v1/chat

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is in the backlog?",
    "workspace_id": "default",
    "user_id": "user",
    "top_k": 25,
    "history_turns": 6
  }'
```

Response: `{"answer": "...sources...", "workspace_id": "default"}`

When `METRONIX_RAG_TRACE_FOOTER_ENABLED=true`, answers may end with `— trace: <uuid>`.

### POST /api/v1/chat/stream

Same body as `/chat`. Returns Server-Sent Events (`text/event-stream`):

```bash
curl -N -X POST http://localhost:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "Summarize last sprint", "workspace_id": "default"}'
```

Events: `token` (text chunks) · `sources` · `done`.

---

## Workspaces

### POST /api/v1/workspaces/

```bash
curl -X POST http://localhost:8000/api/v1/workspaces/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Engineering KB", "description": "Team docs", "user_id": "user"}'
```

### GET /api/v1/workspaces/

```bash
curl "http://localhost:8000/api/v1/workspaces/?user_id=user"
```

### GET /api/v1/workspaces/{workspace_id}

### DELETE /api/v1/workspaces/{workspace_id}?user_id=user

Deletes workspace metadata and attempts Qdrant collection + Neo4j graph cleanup.

### POST /api/v1/workspaces/{workspace_id}/activate?user_id=user

### GET /api/v1/workspaces/{workspace_id}/stats

Returns `file_count`, `chunk_count`, `entity_count`, `jira_issue_count`, `last_upload_time`.

---

## Connections

Connector config is encrypted at rest. List/get responses mask secret fields as `***`.

### GET /api/v1/connections/schemas/

Returns form schemas for all connector types (Confluence, Jira, Notion, GitHub, GDrive, Slack history, files, channels, …).

```bash
curl http://localhost:8000/api/v1/connections/schemas/
```

### POST /api/v1/connections/

```bash
curl -X POST "http://localhost:8000/api/v1/connections/?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "connector_type": "confluence",
    "name": "Confluence Prod",
    "config": {
      "url": "https://acme.atlassian.net/wiki",
      "username": "bot@acme.com",
      "api_token": "ATATT..."
    },
    "sync_cron": "0 3 * * *"
  }'
```

- `sync_cron` — optional cron for autosync (connectors default to `0 3 * * *`; channels ignore it)
- New connectors get `next_run_at=null` → first sync on next scheduler tick

### GET /api/v1/connections/?workspace_id=default&category=connector

### GET /api/v1/connections/{connection_id}/

### GET /api/v1/connections/{connection_id}/reveal-secrets/?workspace_id=default

Editor+. Returns decrypted secrets.

### PUT /api/v1/connections/{connection_id}/

```bash
curl -X PUT "http://localhost:8000/api/v1/connections/CONN_ID/?workspace_id=default" \
  -H "Content-Type: application/json" \
  -d '{"name": "Renamed", "enabled": true, "sync_cron": "0 6 * * *"}'
```

Pass `"sync_cron": ""` to clear the schedule.

### DELETE /api/v1/connections/{connection_id}/

Returns `204`.

### POST /api/v1/connections/{connection_id}/test/

Tests connector configuration. Updates connection status on success/failure.

### POST /api/v1/connections/{connection_id}/sync/

```bash
curl -X POST "http://localhost:8000/api/v1/connections/CONN_ID/sync/?force_full=true" \
  -H "Authorization: Bearer $TOKEN"
```

Query: `force_full=true` — bypass incremental watermark for a one-off full resync.

Response:

```json
{
  "status": "sync_started",
  "sync_id": "sync_abc123",
  "connection_id": "CONN_ID",
  "connector_type": "confluence"
}
```

Errors: `409` if sync already in progress · `400` if connection disabled or not a connector type.

---

## Sync

> **Note:** `/api/v1/sync/status` and `/api/v1/sync/logs` are registered but currently return stub payloads. Use dashboard sync-history or connection `last_synced_at` until implemented.

---

## Documents

### GET /api/v1/documents/{document_id}/history

Paginated version history from PostgreSQL.

```bash
curl "http://localhost:8000/api/v1/documents/doc-123/history?limit=10&offset=0"
```

---

## Graph (KB entity visualization)

Neo4j-backed. Returns `502` when graph DB is unavailable.

### GET /api/v1/graph/overview?workspace_id=default&limit=100

Top connected entities for initial render.

### GET /api/v1/graph/expand/{entity_id}?workspace_id=default&depth=2&limit=50

Expand neighbourhood around a Neo4j internal entity ID.

---

## Memory

Workspace from JWT / `?workspace_id=`. All routes under `/api/v1/memory`.

### POST /api/v1/memory/records — create

```bash
curl -X POST "http://localhost:8000/api/v1/memory/records?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "User prefers dark mode",
    "agent_id": "agent-abc",
    "scope": "PER_AGENT",
    "kind": "preference",
    "importance_score": 0.8,
    "tags": ["ui"]
  }'
```

`scope`: `PER_AGENT` | `SESSION` | `GLOBAL` · `kind`: `fact` | `preference` | `pinned`

SESSION scope requires `session_id` and optional `ttl_expires_at`.

### POST /api/v1/memory/search — hybrid search

Default excludes `archived` and `superseded` when `status_filter` is omitted.

```bash
curl -X POST "http://localhost:8000/api/v1/memory/search?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deployment preferences",
    "agent_id": "agent-abc",
    "top_k": 5
  }'
```

### GET /api/v1/memory/records

List / inspect. **No default status exclusion** (unlike search).

Query: `agent_id`, `scope`, `session_id`, `status_filter[]`, `kind_filter[]`, `limit`, `offset`

When `session_id` is set, returns Redis-backed session records (ignores pagination filters).

### GET /api/v1/memory/records/{record_id}

404 cross-workspace.

### DELETE /api/v1/memory/records/{record_id}

Editor+. Persistent records only (not session cache).

### GET /api/v1/memory/graph

Memory neighbourhood in Neo4j.

Query (required): `seed_record_id` · optional: `depth=1..3`, `agent_id`

Graceful degradation: seed node only, empty edges when Neo4j is down.

### GET /api/v1/memory/review

Freshness review queue. `503` when freshness worker/store not configured.

Query: `reason`, `limit`, `offset`

### POST /api/v1/memory/review/{review_id}

```bash
curl -X POST "http://localhost:8000/api/v1/memory/review/REV_ID?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "keep", "notes": "confirmed duplicate"}'
```

Actions: `keep` · `archive` · `merge_into` (requires `target_record_id`) · `discard`

Returns `204`.

---

## Knowledge (unified inspector)

### GET /api/v1/knowledge/records

Merges agent `memory_records` and KB `raw_documents` at the view layer.

```bash
curl "http://localhost:8000/api/v1/knowledge/records?workspace_id=default&origin=all&lifetime=persistent&limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

| Query | Default | Values |
|---|---|---|
| `origin` | `all` | `agent` · `kb` · `all` |
| `lifetime` | `persistent` | `persistent` · `session` · `all` (agent leg only) |
| `limit` | 50 | 1–200 |
| `offset` | 0 | 0–10000 |

Response includes `partial: bool` and `failed_sources: ["agent"|"kb"]` when one leg fails under `origin=all`. Both legs failing → `503`.

Each record has endpoint-derived `origin: "agent"|"kb"`, optional `session_id`, `ttl_expires_at`.

---

## Agents

Workspace from JWT / `?workspace_id=`. Prefix: `/api/v1/agents`.

### POST /api/v1/agents/

```bash
curl -X POST "http://localhost:8000/api/v1/agents/?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Trader",
    "model": "claude-sonnet-4-6",
    "capabilities": ["trade"],
    "tools": ["memory_search", "memory_store"]
  }'
```

Creates with `status: stopped`, `config_version: 1`.

### GET /api/v1/agents/

Query: `status`, `name_prefix`, `include_archived`, `include_system`, `limit`, `offset`

`status` and `include_archived=true` are mutually exclusive (400).

### PUT /api/v1/agents/{id}

Partial update. Bumps `config_version`, appends version history row.

### DELETE /api/v1/agents/{id}

Soft-delete → `archived`. Returns `204`.

### Lifecycle: POST .../start · .../stop · .../pause

Invalid transitions → `400`.

### POST /api/v1/agents/{id}/restore

`archived` → `stopped`. Only path out of archived state.

### POST /api/v1/agents/{id}/reset

Wipe agent memory. Auto `pre_reset` snapshot first.

Response: `{"snapshot_id": "...", "deleted_count": 42}`

Errors: `413` overflow · `422` corrupt snapshot · `500` with `snapshot_id` in body if wipe fails after snapshot

### POST /api/v1/agents/{id}/snapshots

```bash
curl -X POST "http://localhost:8000/api/v1/agents/AGENT_ID/snapshots?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label": "before migration"}'
```

### GET /api/v1/agents/{id}/snapshots

Newest first.

### GET /api/v1/agents/{id}/versions

Config version history.

### GET /api/v1/agents/{id}/memory/health

Read-only health snapshot: totals, 30-day growth, unused records, duplicate clusters (SimHash), source distribution.

### GET /api/v1/agents/{id}/activity

Paginated activity log. Query: `since`, `until`, `event_type[]`, `session_id`, `correlation_id`, `limit`, `offset`

`503` when `METRONIX_ACTIVITY_LOG_ENABLED=false`.

### GET /api/v1/agents/{id}/activity/summary?period=7d

Aggregates. Period: `1d` · `7d` · `30d` · `90d`.

---

## Snapshots (cross-snapshot ops)

Prefix: `/api/v1/snapshots`. Creation/listing lives under `/api/v1/agents/{id}/snapshots`.

### POST /api/v1/snapshots/{snapshot_id}/restore

Replace agent memory from snapshot. Auto `pre_restore` snapshot taken first.

```bash
curl -X POST "http://localhost:8000/api/v1/snapshots/SNAP_ID/restore?workspace_id=default" \
  -H "Authorization: Bearer $TOKEN"
```

### GET /api/v1/snapshots/diff?from=SNAP_A&to=SNAP_B&key=source

Compare two snapshots of the **same agent**. Cross-agent → `400`.

`key`: `source` (default) or `content_hash`

### GET /api/v1/snapshots/{snapshot_id}/records?ids=id1&ids=id2

Resolve up to 200 record IDs from the snapshot **file** (not live memory). For diff UI lazy-load.

---

## RAG debug traces

Read-only. **Not** gated by `METRONIX_RAG_TRACE_ENABLED`.

### GET /api/v1/traces/

```bash
curl "http://localhost:8000/api/v1/traces/?workspace_id=default&limit=20&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

### GET /api/v1/traces/{trace_id}

Full phased trace JSONB. Malformed UUID → `422`.

---

## Dashboard

All endpoints require `?workspace_id=`.

| Endpoint | Description |
|---|---|
| `GET /api/v1/dashboard/overview` | Documents, Jira issues, active connectors, last upload |
| `GET /api/v1/dashboard/query-trend?days=30` | Daily query counts |
| `GET /api/v1/dashboard/sync-history?limit=10` | Recent sync logs |
| `GET /api/v1/dashboard/ingestion-errors?limit=20` | Failed/partial syncs |
| `GET /api/v1/dashboard/graph-stats` | Neo4j + Qdrant lineage stats |

Example:

```bash
curl "http://localhost:8000/api/v1/dashboard/overview?workspace_id=default"
```

---

## Admin

Prefix: `/api/v1/admin`.

### GET /api/v1/admin/status

Database connectivity summary.

### GET /api/v1/admin/cleanup/preview

Read-only preview of deletable data.

### DELETE /api/v1/admin/cleanup/workspace/{workspace_id}

Requires `ALLOW_CLEANUP=true` and header `X-Confirm-Cleanup: yes`.

### DELETE /api/v1/admin/cleanup/all

Requires `X-Confirm-Cleanup: DELETE-ALL-DATA`.

### POST /api/v1/admin/reindex

**Global** operation — resets sync flags for all workspaces, clears Neo4j graph.

Requires header `X-Confirm-Reindex: yes`.

```bash
curl -X POST http://localhost:8000/api/v1/admin/reindex \
  -H "X-Confirm-Reindex: yes"
```

### POST /api/v1/admin/import-openwebui-users

Admin only. Import users from external Open WebUI.

```bash
curl -X POST http://localhost:8000/api/v1/admin/import-openwebui-users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "owui_url": "http://openwebui.company.com",
    "admin_email": "admin@company.com",
    "admin_password": "password"
  }'
```

---

## Users

Admin only.

### POST /api/v1/users

Creates user + default API key (`mtk_...`). May auto-sync to Open WebUI when configured.

### GET /api/v1/users · GET /api/v1/users/{id} · PATCH · DELETE

### API keys

```bash
# Create (raw key returned once)
curl -X POST "http://localhost:8000/api/v1/users/USER_ID/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label": "cursor"}'

# List (prefix only, no secrets)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/users/USER_ID/api-keys"

# Revoke
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/users/USER_ID/api-keys/mtk_abcd"
```

### Platform mappings

`GET /api/v1/users/platform-mappings` · `GET /api/v1/users/{id}/platform-mappings` · `PUT` · `DELETE`

Telegram/Slack/Discord identity → internal user mapping.

---

## Skills

`/api/v1/skills/` — CRUD for skill definitions. Engine is **inactive** (reserved); prefer MCP tool descriptions for new work.

---

## FinOps

Metrics from `query_traces` and related tables.

```bash
curl "http://localhost:8000/api/v1/finops/time-savings?workspace_id=default&days=30"
curl "http://localhost:8000/api/v1/finops/active-users?workspace_id=default&days=30"
curl "http://localhost:8000/api/v1/finops/cost-savings?workspace_id=default&days=30&limit=100"
```

---

## Benchmarker

Dev/eval tool. Requires optional `benchmark-qed` dependency.

| Method | Path |
|---|---|
| POST | `/api/v1/query/trace` |
| POST | `/api/v1/benchmarker/generate` |
| POST | `/api/v1/benchmarker/run-tests` |
| GET/POST/DELETE | `/api/v1/benchmarker/benchmarks` and `.../benchmarks/{id}` |
| POST | `/api/v1/benchmarker/benchmarks/{id}/clone` |
| GET/POST/DELETE | `/api/v1/benchmarker/test-runs` and `.../test-runs/{id}` |

All benchmarker endpoints require `?workspace_id=`.

Example trace:

```bash
curl -X POST http://localhost:8000/api/v1/query/trace \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "default",
    "query": "What tasks are in backlog?",
    "options": {"max_results": 10, "include_sources": true}
  }'
```

---

## OpenAI-compatible API

Enabled when `METRONIX_OPENAI_COMPAT_ENABLED=true`.

Auth: `Authorization: Bearer mtk_...` or static `METRONIX_OPENAI_COMPAT_KEY`.

Error shape: `{"error": {"message": "...", "type": "invalid_request_error"}}`

### GET /v1/models

Each workspace → one model `metronix-rag-{workspace_id}`.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/models
```

### POST /v1/chat/completions

Runs hybrid RAG internally (not a raw LLM proxy). `temperature`, `max_tokens`, etc. are accepted but ignored.

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "metronix-rag-default",
    "messages": [{"role": "user", "content": "What is in the backlog?"}],
    "stream": false
  }'
```

Streaming: set `"stream": true` → SSE chunks in OpenAI format, terminated with `data: [DONE]`.

### GET /v1/openapi.json

Connection verification stub for Open WebUI.

### POST /v1/proxy/chat/completions

Optional LLM proxy surface (when mounted). Same auth as OpenAI-compat.

---

## Error responses

FastAPI default:

```json
{"detail": "Human-readable message"}
```

OpenAI-compat endpoints:

```json
{"error": {"message": "...", "type": "invalid_request_error"}}
```

Common status codes:

| Code | Meaning |
|---|---|
| 200 | OK |
| 201 | Created |
| 204 | No content (delete/resolve) |
| 207 | Multi-status (partial upload success) |
| 400 | Bad request / invalid transition |
| 401 | Unauthenticated |
| 403 | Forbidden (RBAC / workspace) |
| 404 | Not found (includes cross-workspace isolation) |
| 409 | Conflict (duplicate sync, name collision) |
| 413 | Payload too large (snapshot overflow) |
| 422 | Validation error |
| 503 | Dependency unavailable (Neo4j, freshness store, activity log) |

---

## Related docs

- [`docs/MCP_API.md`](MCP_API.md) — MCP tools (`memory_*`, `metronix_search`, …)
- [`docs/integrations/hermes.md`](integrations/hermes.md) — external agent setup
