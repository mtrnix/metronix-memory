# Data Export — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorming) — ready for implementation plan
**Branch:** `feat/data-export`

## Problem

A user who is leaving Metronix needs to take all of their data out before deleting
the instance. Today there is no way to do this: data lives across PostgreSQL
(`memory_records`, `raw_documents`), Qdrant (chunks), and Neo4j (graph), and the
only read paths are paginated list endpoints meant for live use.

The user must be able to retrieve, in human-usable form:

1. **All agent memory** — one Markdown file per agent (`<agent_id>.md`), covering
   every agent that has memory, **including unregistered agents** (agents that
   invented their own `agent_id` and stored memory without ever being registered in
   the `agents` table).
2. **All ingested data** — files, connector items (Jira tasks, Confluence pages,
   etc.) reconstructed in their **original whole form** (the full document as it was
   fed into Metronix), **not** the embedding chunks.

## Goals

- Export is triggered by an agent over MCP, or by a human over REST.
- The export is delivered as a single ZIP archive the agent/user can download,
  unzip, and work with locally.
- Download requires **only a one-time token embedded in the URL** — no JWT, no API
  key header.
- Build runs in the **background**; trigger returns immediately and the caller polls
  for readiness.

## Non-Goals

- Re-emitting original uploaded-file **bytes** (PDF/DOCX). Metronix stores only the
  extracted text of uploads (`raw_documents.content`), not the original binary. We
  export the extracted text and flag this limitation explicitly. Connector items and
  their full text/metadata are fully recoverable.
- Exporting embedding vectors, Qdrant chunks, or the Neo4j graph. The source of
  truth for both memory and documents is PostgreSQL, which is sufficient to
  reconstruct everything in original form.
- Deleting data (this is export only). Account/instance teardown is separate.

## Key Findings From the Codebase

- **MCP tools:** added as a file in `src/metronix/mcp/tools/`, decorated with
  `@mcp.tool(...)`, exported from `src/metronix/mcp/tools/__init__.py`. Auth is a
  single Bearer token (`METRONIX_MCP_API_KEY`) — effectively admin. `workspace_id`
  and `agent_id` are passed as tool parameters by the caller.
- **REST:** routers in `src/metronix/api/routes/`, registered in
  `src/metronix/api/app.py`. Workspace access is enforced via the existing
  `resolve_workspace_id` / `workspace_scope` dependencies (JWT, with `*` = admin).
- **Memory:** source of truth is the PostgreSQL `memory_records` table
  (`src/metronix/storage/memory_postgres.py`). `agent_id` is a plain `Text` column
  with **no foreign key** — unregistered agents are first-class. Distinct agents are
  enumerable via `SELECT DISTINCT agent_id FROM memory_records WHERE workspace_id = :ws`.
  `MemoryPostgresStore.list_records(workspace_id, agent_id=...)` already fetches all
  records for an agent. `list_workspaces()` already returns distinct workspace ids.
- **Documents:** the `raw_documents` table holds the **full original content**
  (pre-chunk) plus `title`, `url`, `author`, `source_id`, `connector_type`, and
  `metadata` (JSONB). Connector items are fully recoverable. Chunks/embeddings live
  in Qdrant and are not needed for export.
- **No existing export/dump functionality.**

## Architecture

A single `ExportService` owns all build logic. MCP and REST are thin surfaces over
it. Build is asynchronous; an export job has a lifecycle and a one-time download
token minted on completion.

### Deployment & process model (invariant)

This feature targets the **HTTP API deployment**, where the MCP server is mounted
into the same FastAPI/uvicorn process as REST (`api/app.py:601-610` adds the `/mcp`
route to the API app; the default docker-compose serves both `/mcp` and `/api/v1`
on `:8001`). The standalone `python -m metronix.mcp --transport stdio` mode
(`mcp/__main__.py`) is an **ephemeral process with no co-located REST server** and
therefore cannot deliver a download URL — export is **out of scope for stdio-only
MCP**; the trigger requires the HTTP API to be reachable.

Even within the single API process, the build must outlive the request that
triggered it and survive an API restart. Invariant: **trigger, build, and download
communicate only through durable shared state — a PostgreSQL `export_jobs` row, the
one-time token in Redis, and the ZIP on a shared volume.** Nothing is held in the
memory of the triggering request.

This resolves the background mechanism (no longer 50/50): the build runs as an
**in-process `asyncio` task on the API process**, but its authoritative state lives
in the `export_jobs` table — **not** FastAPI `BackgroundTasks` (which run only
post-response, die on restart, and are unavailable on the MCP path — there is no
`Request`). On startup the API runs a **watchdog**: any job left `running` past a
timeout is marked `failed` so it never sticks in limbo.

```text
MCP  metronix_export_data ─┐
                           ├─► ExportService.start(scope) ─► job(export_id, status=pending)
REST POST /api/v1/export ──┘                                      │
                                                                  ▼ (background task)
                                          enumerate workspaces / agents / documents
                                          render markdown + manifest → write ZIP to volume
                                          mint one-time token → status=ready
MCP  metronix_export_status ─┐
                             ├─► ExportService.status(export_id) ─► {status, download_url?, counts, size}
REST GET /api/v1/export/{id} ┘

REST GET /api/v1/export/{id}/download?token=<one-time>  ─► stream application/zip, consume token
```

### Components

- **`ExportService`** (`src/metronix/export/service.py`)
  - `start(scope) -> export_id`: create job record, set `status=pending`, schedule
    the background build, return immediately.
  - `status(export_id) -> ExportJob`: return current status and, when ready, the
    `download_url`, counts, and size.
  - `_build(export_id, scope)`: the background routine that produces the archive.
- **Renderers** (`src/metronix/export/render.py`)
  - `render_agent_memory(agent_id, records) -> str` (Markdown).
  - `render_document(doc) -> (relative_path, str)` (Markdown with YAML front matter).
  - `build_manifest(scope, files, notes) -> dict`.
- **Archive writer** (`src/metronix/export/archive.py`): streams entries into a ZIP
  on the mounted volume (`{export_dir}/<export_id>.zip`, default
  `/app/data/exports`).
- **Job store**: a PostgreSQL `export_jobs` table is the source of truth for job
  state — `export_id` (PK), `scope` (JSONB), `scope_key`, `status`
  (`pending|running|ready|failed`), counts, `size_bytes`, `archive_path`,
  `download_token`, `error`, `created_at`, `updated_at`. It must be durable (survive
  an API restart) and readable by any worker; Redis is not durable enough for this.
  A **UNIQUE partial index** on `scope_key WHERE status IN ('pending','running')`
  lets the DB enforce one active job per scope (see Concurrency).
- **Token store**: one-time download tokens in Redis — `export_token:<token>` →
  `{export_id, path}`, TTL (default 1 hour). The token is generated with a CSPRNG,
  ≥128 bits of entropy (`secrets.token_urlsafe(32)`). It is **minted once when the
  build completes** and stored on the job row (`export_jobs.download_token`), so
  repeated `status` polling reuses the same token rather than minting a new valid one
  each call. It is consumed (deleted from Redis) on the first successful download.
  The download route must keep the token out of access logs (do not log the query
  string for this path).
- **MCP tools** (`src/metronix/mcp/tools/export.py`):
  `metronix_export_data(workspace_id?, all_workspaces=false)` and
  `metronix_export_status(export_id)`.
- **REST router** (`src/metronix/api/routes/export.py`):
  `POST /api/v1/export`, `GET /api/v1/export/{export_id}`,
  `GET /api/v1/export/{export_id}/download`.

### Surfaces and scope

- **Scope** (`all_workspaces` flag): exports either one workspace or every workspace
  in one archive.
  - MCP: `metronix_export_data(workspace_id?, all_workspaces=false)`. **No silent
    `"default"` fallback** — unlike the other MCP tools, which coerce
    `workspace_id or "default"` (e.g. `mcp/tools/memory_store.py:91`), this tool
    requires an explicit `workspace_id` **or** `all_workspaces=true`; otherwise it
    returns an `INVALID_PARAMS` error. A bare call must never dump only the
    `"default"` workspace by accident. The single MCP API key is already admin, so
    `all_workspaces` needs no extra gate here.
  - REST: `all_workspaces=true` requires an admin caller (JWT workspace access `*`),
    reusing existing RBAC; a single-workspace export uses the normal
    `resolve_workspace_id` check. No new auth mechanism is introduced.
- **Status** (`GET /export/{id}`): authorizes the caller against the *job's* scope
  before returning anything — an `all_workspaces` export is admin-only, a
  single-workspace export requires the caller to have access to that workspace.
  Without this, any authenticated user could poll an arbitrary `export_id` and be
  handed a download token for another workspace's archive. (The MCP `…_status` tool
  runs under the single admin API key and is unrestricted.)
- **Download** (`GET .../download?token=`): authorized **solely** by the one-time
  token in the URL. No JWT, no API-key header. The token is the capability; it is
  only ever handed out by the authorized `status` path above.

### Configuration

Building an absolute `download_url` needs the API's public base URL. No suitable
setting exists today — `core/config.py` only has `freshness_llm_api_base_url:278`.
Add a new setting (e.g. `public_base_url`); the `download_url` is
`{public_base_url}/api/v1/export/{export_id}/download?token=<token>`. If unset, fall
back to the request's own base URL on the REST path; the MCP path requires it to be
configured (no request to derive it from).

`export_dir` (default `/app/data/exports`) must sit on the persistent volume —
docker-compose mounts `full_file_data:/app/data`, so a bare `/data` would be
ephemeral and lose archives on restart and across workers.

## Archive Layout

```text
metronix-export-<timestamp>.zip
├── manifest.json
├── <workspace_id>/
│   ├── memory/
│   │   ├── <safe-agent-id>.md          # one file per distinct agent_id with memory
│   │   └── ...
│   └── documents/
│       ├── jira/<source_id>.md         # full original content + metadata header
│       ├── confluence/<source_id>.md
│       ├── uploads/<filename>.md       # extracted text only (original bytes not stored)
│       └── <connector_type>/...
└── (repeats per workspace when all_workspaces=true)
```

### `manifest.json`

```json
{
  "format_version": 1,
  "generated_at": "2026-06-24T12:00:00Z",
  "scope": { "all_workspaces": false, "workspaces": ["<workspace_id>"] },
  "counts": { "workspaces": 1, "agents": 12, "memory_records": 480, "documents": 1500 },
  "agents": [
    { "agent_id": "<real agent_id>", "file": "memory/<safe-agent-id>.md", "registered": false, "record_count": 37 }
  ],
  "limitations": [
    "Uploaded files are exported as extracted text only; original binary files are not retained by Metronix."
  ]
}
```

### Markdown formats

- **Agent memory `<agent_id>.md`**: header (real `agent_id`, workspace, record count,
  generated-at) followed by one section per record with key fields — `kind`, `scope`,
  `status`, `created_at`, `updated_at`, `tags`, `importance_score`, then `content`.
- **Document `<source_id>.md`**: YAML front matter (`title`, `url`, `author`,
  `source_id`, `connector_type`, selected `metadata`) followed by the full
  `raw_documents.content`.

## Filename Safety

`agent_id`, `connector_type`, `source_id`, and upload filenames are all arbitrary
strings (unregistered agents invent their own `agent_id`; connector/source ids and
filenames may contain `/`, `..`, or other unsafe characters). **Every path segment**
written into the archive — directory names (`<connector_type>/`) and file names
alike — is slugified to a filesystem-safe form to prevent path traversal; on
collision a short stable hash suffix is appended. The **real** identifier is always
preserved inside the file and in `manifest.json`, so slugification is never lossy.

### What memory is included

`MemoryPostgresStore.list_records` defaults to `status=None` and `lifetime="all"`
(`storage/memory_postgres.py:273-274`), i.e. **no filter**. Export must be explicit
rather than relying on those defaults:

- Include **persistent** records (`lifetime="persistent"`, `ttl_expires_at IS NULL`)
  of **all lifecycle statuses** (active, stale, superseded, archived, conflicted,
  review-needed) — "take everything I own". The record's `status` is written into the
  `.md` so the user can see it.
- **Exclude** session/TTL records (`ttl_expires_at IS NOT NULL`) — these are ephemeral
  working memory, may be expired-but-not-yet-GC'd, and are not part of the durable
  knowledge a leaving user wants.

## Data Flow (build)

1. Resolve scope → list of `workspace_id`s (one, or all via `list_workspaces()`).
2. For each workspace:
   a. `SELECT DISTINCT agent_id FROM memory_records WHERE workspace_id = :ws` →
      every agent with memory (registered or not). For each, page through
      `list_records(ws, agent_id=..., lifetime="persistent")` to bound memory, render
      `<agent_id>.md`.
   b. Page through `raw_documents` for the workspace and render one Markdown file per
      row grouped by `connector_type`. Use **keyset pagination** on the existing
      stable order `(updated_at DESC, id ASC)` (`storage/postgres.py:1401`) rather
      than `OFFSET`, so concurrent writes during a long export can't cause rows to be
      skipped or duplicated.
3. Cross-reference the `agents` table only to set the `registered` flag in the
   manifest (not required for inclusion).
4. Write all entries to the ZIP on the volume; compute counts and size.
5. Mint the one-time token (store `{export_id, path}` in Redis with TTL), persist it
   and the counts/size/path on the `export_jobs` row, and set `status=ready`. The
   token lives on the job so `status` can return the same `download_url` on every
   poll instead of minting a fresh token each time.

## Error Handling

- **Unknown/expired `export_id`** → status `not_found` / 404.
- **Build failure** → job `status=failed` with an error summary; surfaced via status
  tool/endpoint.
- **Status for an export the caller can't access** → 403 (scope authorization, see
  Surfaces) — checked before any token is minted or returned.
- **Download with missing/used/expired token** → 404 (do not distinguish reasons, to
  avoid leaking existence).
- **Token valid but ZIP already cleaned up** → 410 Gone.
- **Empty workspace / no memory** → valid empty-ish archive with a manifest note, not
  an error.
- **Large exports** → background build avoids request timeouts; memory bounded by
  paginating both `memory_records` and `raw_documents` and streaming into the ZIP.

## Concurrency & Quota

- **One active job per scope:** `start` first checks `export_jobs` for an existing
  `pending`/`running` job with the same `scope_key` and returns it if present. To
  close the check-then-create race, the **UNIQUE partial index** also rejects a
  second active insert at the DB level; `start` catches the resulting
  `IntegrityError` and returns the winning job. This dedups repeated triggers and
  stops a single agent from spawning many parallel multi-GB builds.
- **Disk cap on `export_dir`:** enforce a configurable ceiling; if exceeded, reject
  new jobs with a clear error and rely on cleanup (below) to free space.

## Token & Archive Lifecycle

- One-time token TTL: default 1 hour (configurable).
- Token consumed on first successful download.
- ZIP files older than the TTL are cleaned up (lazy on access plus a periodic sweep
  reusing the existing scheduler); the same sweep removes archives for `failed` jobs.

## Testing (TDD)

- **Unit — renderers:** agent-memory Markdown (incl. all fields), document Markdown
  with front matter, manifest shape, filename slugification + collision suffix.
- **Unit — enumeration:** distinct-agent query includes unregistered agents; empty
  workspace yields a valid manifest.
- **Unit — token:** one-time semantics (second download → 404), TTL expiry, cleaned
  archive → 410.
- **Integration — REST:** `POST` returns `export_id`; polling `GET` reaches `ready`;
  `download` streams a valid ZIP whose contents match the manifest; `all_workspaces`
  admin gate enforced.
- **Integration — MCP:** `metronix_export_data` requires an explicit `workspace_id`
  or `all_workspaces=true` (bare call → `INVALID_PARAMS`, never silently `"default"`);
  returns an `export_id`; `metronix_export_status` returns a working `download_url`
  once ready.
- **Restart/watchdog:** a job left `running` past the timeout is marked `failed` on
  startup, never stuck in limbo.
- **Concurrency:** a second trigger for the same scope returns the existing
  `export_id` rather than starting a parallel build.

## Decisions (resolved from review)

- Job state store: PostgreSQL `export_jobs` table (durable, survives restart). Redis
  holds only the short-lived one-time download token.
- Background mechanism: in-process `asyncio` task on the API process with state in
  `export_jobs`; **not** FastAPI `BackgroundTasks` (post-response only, die on
  restart, unavailable on the MCP path). Startup watchdog reaps orphaned `running`
  jobs.
- `download_url` base: new `public_base_url` setting (none exists today); REST may
  fall back to the request base URL, MCP requires it configured.
- Archive cleanup: lazy-on-access plus a periodic sweep on the existing scheduler.

## Open Items for Planning

- Exact `export_jobs` columns/migration and the watchdog timeout value.
- Default disk-cap value for `export_dir`.
- Whether the periodic sweep is a new scheduled job or folds into an existing one.
