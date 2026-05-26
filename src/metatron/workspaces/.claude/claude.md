# Workspaces

## Overview
L3 — workspace isolation layer. Every query, document, chunk, and connection is
scoped to a `workspace_id`. Manages workspace CRUD with optional Neo4j persistence
and PostgreSQL sync for FK integrity.

## Files

### `models.py`
`Workspace` dataclass — `id`, `name`, `slug`, `description`, `created_at`, `is_active`, `config: dict`.
`WorkspaceStats` — `document_count`, `chunk_count`, `query_count`, `last_activity_at`.
`WorkspaceSetting` — key-value config entry for a workspace.

### `manager.py`
`WorkspaceManager` — thread-safe CRUD with layered storage.

Primary store: **in-memory dict** `{workspace_id: Workspace}`.
Optional persistence: **Neo4j** (Cypher MERGE/MATCH on `:Workspace` nodes).
FK sync: **PostgreSQL** (ensures workspace_id exists before documents/chunks reference it).

`create_workspace(name, description, user_id, workspace_id) -> Workspace`
`get_workspace(workspace_id) -> Workspace | None`
`list_workspaces(user_id) -> list[Workspace]`
`update_workspace(workspace_id, **kwargs) -> Workspace`
`delete_workspace(workspace_id)` — soft delete (sets `is_active=False`)
`get_or_create_default() -> Workspace` — returns workspace for `DEFAULT_WORKSPACE_ID`

Singleton via `get_workspace_manager()` — module-level instance created on first call.

### `persistence.py`
`Neo4jWorkspacePersistence` — Cypher operations for workspace graph nodes.

Node labels: `:Workspace`, `:WorkspaceStats`, `:WorkspaceSetting`.
All operations use `MERGE` for idempotency.
`@with_retry(3)` decorator — retries on Neo4j connection errors (reconnects on failure).

`save_workspace(workspace)` — MERGE `:Workspace` node with all properties
`load_workspace(workspace_id) -> dict | None` — MATCH + RETURN
`save_stats(workspace_id, stats)` — MERGE `:WorkspaceStats` linked to workspace
`list_workspaces() -> list[dict]` — MATCH all `:Workspace` nodes

## bootstrap/ sub-package (ASOC pilot — T2 + T7, MTRNIX-352 + MTRNIX-357)

External-driven workspace lifecycle for ASOC-provisioned workspaces. ASOC calls the admin
REST endpoints; this sub-package manages the `bootstrap_state` table and the asynchronous
bootstrap/sync machinery.

### `models.py`
- `BootstrapStateEnum(StrEnum)` — `BOOTSTRAPPING`, `READY`, `FAILED` (archive = hard
  delete in the ASOC pilot — there is no separate ARCHIVED state)
- `BootstrapState` (frozen dataclass) — mirrors the `bootstrap_state` DB table exactly:
  `workspace_id`, `state`, `progress`, `current_step`, `last_processed_resource`,
  `last_processed_id`, `indexed_count`, `total_count`, `last_error`, `last_synced_at`,
  `retry_count`, `next_retry_at`, `updated_at`

### `store.py`
`BootstrapStateStore` — async PostgreSQL DAO for the `bootstrap_state` table.

Key methods:
- `get(workspace_id) -> BootstrapState | None`
- `create(workspace_id, state, config?) -> BootstrapState`
- `update(workspace_id, **fields) -> BootstrapState`
- `delete(workspace_id)`
- `list_ready() -> list[BootstrapState]` — used by AsocSyncCron
- `list_failed_for_retry(now) -> list[BootstrapState]` — `state=failed AND next_retry_at <= now`
- `reclaim_stale_bootstrapping(stale_threshold_seconds) -> int` — reclaim rows stuck in
  `bootstrapping` state (e.g. after a crash) at startup; returns reclaimed count

### `job.py`
`BootstrapJob` — runs the full initial index for one workspace. Resumable via checkpoint
(`last_processed_resource` / `last_processed_id` saved after every batch). Uses
`AsocConnector.fetch(workspace_id, since=None)` for full pull; updates `bootstrap_state`
after each batch. On completion: `state = READY`. On exception: `state = FAILED` with
`last_error` populated.

### `runner.py`
`BootstrapRunner` — thin wrapper that constructs `BootstrapJob` with the correct connector
and ingestion pipeline instance, then calls `job.run()`. Used by `cron.py` and the
workspace manager's `bootstrap()` method.

### `cron.py` (BootstrapRetryCron)
`BootstrapRetryCron` — periodic retry loop for `FAILED` workspaces.
- Polls every `METATRON_ASOC_BOOTSTRAP_RETRY_INTERVAL_SECONDS` (default 60 s).
- Finds rows with `state=failed AND next_retry_at <= now()`.
- Calls `BootstrapRunner.run(workspace_id)` with exponential backoff:
  `delay = METATRON_ASOC_BOOTSTRAP_RETRY_BACKOFF_BASE_SECONDS * 2^(retry_count-1)`.
- Capped at `METATRON_ASOC_BOOTSTRAP_RETRY_MAX_ATTEMPTS`.
- Launched as `asyncio.create_task` in the app lifespan.

### `sync_cron.py` (AsocSyncCron, T7, MTRNIX-357)
`AsocSyncCron` — periodic delta-sync loop for `READY` workspaces.
- Polls every `METATRON_ASOC_SYNC_INTERVAL_SECONDS` (default 900 s = 15 min).
- Queries `list_ready()` → for each workspace: `AsocConnector.fetch(since=last_synced_at)` →
  ingests delta documents → updates `last_synced_at` on success.
- Bounded concurrency via semaphore: `METATRON_ASOC_SYNC_MAX_CONCURRENT_WORKSPACES` (default 3).
- Only `READY` workspaces are synced; `BOOTSTRAPPING` and `FAILED` are skipped.
  Archived workspaces don't exist as a state — `DELETE /workspace/{id}` is a hard delete.
- Per-workspace failures do NOT abort the cron; logged and loop continues.
- Launched as `asyncio.create_task` in the app lifespan (alongside `BootstrapRetryCron`).
- Multi-replica safety is deferred to Phase 2; MVP is single-replica, idempotent via content-hash dedup.

## Key Patterns
- **Workspace isolation** — all storage queries are filtered by `workspace_id` (passed as argument, never inferred)
- **In-memory primary + optional persistence** — works without Neo4j; persistence is additive
- **`get_workspace_manager()` singleton** — import and call this, never instantiate `WorkspaceManager` directly in app code
- **PostgreSQL FK sync** — `manager.py` upserts workspace row into PostgreSQL before any storage operations that reference `workspace_id`
- **Resumable bootstrap** — checkpoint written to `bootstrap_state` after every batch; crash recovery restarts from last checkpoint
- **Idempotent cron launch** — both crons are `asyncio.create_task` in the app lifespan; restarting the app re-creates them without DB side effects

## Dependencies
- **Depends on**: `core.models` (Workspace), `core.config` (Settings), `storage.neo4j_graph`, `storage.postgres`
- **Depended on by**: `api.routes.workspaces`, `api.routes.dashboard.overview`, `retrieval.search` (workspace_id scoping), `ingestion.pipeline`, `connectors` (workspace_id on Document)
- **bootstrap/ additionally depended on by**: `api.routes.asoc_workspace` (T2 endpoint), `chat.asoc_orchestrator` (T4 — reads `bootstrap_state` to verify workspace is READY before answering)
