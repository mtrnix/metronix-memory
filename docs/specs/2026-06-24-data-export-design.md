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
  on the mounted volume (e.g. `/data/exports/<export_id>.zip`).
- **Token store**: one-time tokens in Redis — `export_token:<token>` →
  `{export_id, path}`, TTL (default 1 hour). Consumed (deleted) on first successful
  download. Job state (`status`, counts, size, error) is stored in Redis (or a small
  PostgreSQL table) keyed by `export_id`; exact store decided during planning to
  match existing patterns.
- **MCP tools** (`src/metronix/mcp/tools/export.py`):
  `metronix_export_data(workspace_id?, all_workspaces=false)` and
  `metronix_export_status(export_id)`.
- **REST router** (`src/metronix/api/routes/export.py`):
  `POST /api/v1/export`, `GET /api/v1/export/{export_id}`,
  `GET /api/v1/export/{export_id}/download`.

### Surfaces and scope

- **Scope** (`all_workspaces` flag): default is the caller's single `workspace_id`.
  `all_workspaces=true` exports every workspace in one archive.
  - MCP: freely available — the single MCP API key is already admin.
  - REST: `all_workspaces=true` requires an admin caller (JWT workspace access `*`),
    reusing existing RBAC; a single-workspace export uses the normal
    `resolve_workspace_id` check. No new auth mechanism is introduced.
- **Download** (`GET .../download?token=`): authorized **solely** by the one-time
  token in the URL. No JWT, no API-key header.

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

`agent_id` and document identifiers are arbitrary strings (unregistered agents
invent their own; connector ids may contain unsafe characters). File/dir names are
slugified to a filesystem-safe form; on collision a short stable hash suffix is
appended. The **real** identifier is always preserved inside the file and in
`manifest.json`, so slugification is never lossy.

## Data Flow (build)

1. Resolve scope → list of `workspace_id`s (one, or all via `list_workspaces()`).
2. For each workspace:
   a. `SELECT DISTINCT agent_id FROM memory_records WHERE workspace_id = :ws` →
      every agent with memory (registered or not). For each, `list_records(ws, agent_id=...)`
      (paginated to bound memory), render `<agent_id>.md`.
   b. Enumerate `raw_documents` for the workspace (paginated), render one Markdown
      file per row grouped by `connector_type`.
3. Cross-reference the `agents` table only to set the `registered` flag in the
   manifest (not required for inclusion).
4. Write all entries to the ZIP on the volume; compute counts and size.
5. Mint a one-time token, store `{export_id, path}` in Redis with TTL; set
   `status=ready` and `download_url`.

## Error Handling

- **Unknown/expired `export_id`** → status `not_found` / 404.
- **Build failure** → job `status=failed` with an error summary; surfaced via status
  tool/endpoint.
- **Download with missing/used/expired token** → 404 (do not distinguish reasons, to
  avoid leaking existence).
- **Token valid but ZIP already cleaned up** → 410 Gone.
- **Empty workspace / no memory** → valid empty-ish archive with a manifest note, not
  an error.
- **Large exports** → background build avoids request timeouts; memory bounded by
  paginating both `memory_records` and `raw_documents` and streaming into the ZIP.

## Token & Archive Lifecycle

- One-time token TTL: default 1 hour (configurable).
- Token consumed on first successful download.
- ZIP files older than the TTL are cleaned up (lazy on access and/or a periodic
  sweep); cleanup mechanism finalized during planning.

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
- **Integration — MCP:** `metronix_export_data` returns an `export_id`;
  `metronix_export_status` returns a working `download_url` once ready.

## Open Items for Planning

- Job/state store choice: Redis vs a small PostgreSQL `export_jobs` table.
- Background execution mechanism: in-process `asyncio` task vs existing scheduler.
- `public_base_url` configuration for building absolute `download_url`s.
- Archive cleanup trigger (lazy vs periodic sweep).
