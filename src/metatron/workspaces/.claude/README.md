# Workspaces

## Overview
L3 — workspace isolation layer. Every query, document, chunk, and connection is
scoped to a `workspace_id`. Manages workspace CRUD with optional Memgraph persistence
and PostgreSQL sync for FK integrity.

## Files

### `models.py`
`Workspace` dataclass — `id`, `name`, `slug`, `description`, `created_at`, `is_active`, `config: dict`.
`WorkspaceStats` — `document_count`, `chunk_count`, `query_count`, `last_activity_at`.
`WorkspaceSetting` — key-value config entry for a workspace.

### `manager.py`
`WorkspaceManager` — thread-safe CRUD with layered storage.

Primary store: **in-memory dict** `{workspace_id: Workspace}`.
Optional persistence: **Memgraph** (Cypher MERGE/MATCH on `:Workspace` nodes).
FK sync: **PostgreSQL** (ensures workspace_id exists before documents/chunks reference it).

`create_workspace(name, description, user_id, workspace_id) -> Workspace`
`get_workspace(workspace_id) -> Workspace | None`
`list_workspaces(user_id) -> list[Workspace]`
`update_workspace(workspace_id, **kwargs) -> Workspace`
`delete_workspace(workspace_id)` — soft delete (sets `is_active=False`)
`get_or_create_default() -> Workspace` — returns workspace for `DEFAULT_WORKSPACE_ID`

Singleton via `get_workspace_manager()` — module-level instance created on first call.

### `persistence.py`
`MemgraphWorkspacePersistence` — Cypher operations for workspace graph nodes.

Node labels: `:Workspace`, `:WorkspaceStats`, `:WorkspaceSetting`.
All operations use `MERGE` for idempotency.
`@with_retry(3)` decorator — retries on Memgraph connection errors (reconnects on failure).

`save_workspace(workspace)` — MERGE `:Workspace` node with all properties
`load_workspace(workspace_id) -> dict | None` — MATCH + RETURN
`save_stats(workspace_id, stats)` — MERGE `:WorkspaceStats` linked to workspace
`list_workspaces() -> list[dict]` — MATCH all `:Workspace` nodes

## Key Patterns
- **Workspace isolation** — all storage queries are filtered by `workspace_id` (passed as argument, never inferred)
- **In-memory primary + optional persistence** — works without Memgraph; persistence is additive
- **`get_workspace_manager()` singleton** — import and call this, never instantiate `WorkspaceManager` directly in app code
- **PostgreSQL FK sync** — `manager.py` upserts workspace row into PostgreSQL before any storage operations that reference `workspace_id`

## Dependencies
- **Depends on**: `core.models` (Workspace), `core.config` (Settings), `storage.memgraph`, `storage.postgres`
- **Depended on by**: `api.routes.workspaces`, `api.routes.dashboard.overview`, `retrieval.search` (workspace_id scoping), `ingestion.pipeline`, `connectors` (workspace_id on Document)
