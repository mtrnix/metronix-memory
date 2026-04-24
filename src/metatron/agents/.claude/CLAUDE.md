# Agents (Registry)

## Overview
L3 — service layer for the Agent Registry (WS4). Sits next to `memory/`, `llm/`,
`workspaces/`. Provides CRUD, soft-delete, lifecycle flagging, and config-version
history for agents registered in a workspace. PostgreSQL is the only persistence
backend; no Qdrant / Neo4j / Redis touches.

The registry powers the backend half of the Control Center; the UI for this
module lives outside this repo. REST endpoints are exposed at `/api/v1/agents`.

## Files

### `models.py`
Pure dataclasses. Zero business logic.

- `AgentStatus(StrEnum)` — `ACTIVE | PAUSED | STOPPED | ARCHIVED`
- `AgentRecord` — id, workspace_id, name, status, model, capabilities, tools,
  memory_bindings (opaque dict), budget (opaque dict), config_version,
  current_config (snapshot dict), created_by, created_at, updated_at
- `AgentConfigVersion` — agent_id, version, config (snapshot dict), changed_by,
  changed_at

### `persistence.py`
`AgentPersistence(engine: AsyncEngine)` — async PostgreSQL store, raw SQL via
SQLAlchemy (same pattern as `storage/memory_postgres.py`).

Methods (all async):
- `save_new(record) -> AgentRecord` — single transaction: INSERT agent +
  INSERT version row (v=1). Raises `_AgentNameConflictError` (module-private)
  on unique constraint collision. The service layer re-raises it as the
  typed `AgentNameConflictError`.
- `get(workspace_id, agent_id) -> AgentRecord | None`
- `list_records(workspace_id, *, status?, name_prefix?, limit=50, offset=0)`
- `update_with_version_bump(workspace_id, agent_id, *, new_fields, changed_by)`
  — single transaction: `SELECT … FOR UPDATE` → merge → UPDATE agents
  (bump version, update snapshot) → INSERT version row. Returns updated
  record or `None` if not found. Raises `_AgentNameConflictError` on name
  collision.
- `update_status(workspace_id, agent_id, status)` — no version bump.
- `list_versions(workspace_id, agent_id, *, limit=50, offset=0)` — JOINs
  `agents` to enforce workspace isolation.

### `service.py`
`AgentRegistryService(repo, *, workspace_id)` — workspace-bound orchestration.

- `create_agent(*, name, model, capabilities?, tools?, memory_bindings?, budget?, created_by)`
  — forces status=STOPPED, version=1, snapshot reflects payload.
- `get_agent(agent_id)` — 404 via `AgentNotFoundError`.
- `list_agents(*, status?, name_prefix?, limit?, offset?)`
- `update_agent(agent_id, *, name?, model?, capabilities?, tools?, memory_bindings?, budget?, changed_by)`
  — partial merge; full snapshot is re-computed and stored in both
  `current_config` and the new version row.
- `delete_agent(agent_id)` — soft-delete (status → ARCHIVED).
- `start_agent` / `stop_agent` / `pause_agent` — lifecycle transitions, no
  version bump.
- `list_versions(agent_id, *, limit?, offset?)` — pre-checks the agent
  exists so unknown ids raise 404 rather than returning `[]`.

Typed errors:
- `AgentNotFoundError(MetatronError)` — mapped to HTTP 404 by routes.
- `AgentNameConflictError(MetatronError)` — mapped to HTTP 409 by routes.

## Layer Rules
- Can import from: `core/` (L0). Uses `sqlalchemy` (async engine) directly,
  same pattern as `storage/memory_postgres.py`.
- Must NOT import from: `agent/`, `channels/`, `api/`.

## RBAC
Aligns with the `memory/` convention:

- **viewer+** — read-only endpoints (`GET /`, `GET /{id}`, `GET /{id}/versions`)
- **editor+** — writes and lifecycle (`POST /`, `PUT /{id}`, `DELETE /{id}`,
  `POST /{id}/start|stop|pause`)

## Key Decisions
- **Opaque `memory_bindings` and `budget`** — the registry stores JSONB but
  does not interpret shape. Consumer schemas (memory service, future scheduler)
  own the contract.
- **Lifecycle is DB-only** — start/stop/pause flip the `status` flag; no
  process control, no scheduler coupling. A separate service will observe
  status changes and act. `_transition_status` does not validate the
  source → target edge, so `POST /start` on an archived agent transitions
  it back to ACTIVE — effectively an un-delete. UX decision pending under
  MTRNIX-323; callers doing DELETE → retry → /start should be aware.
- **Versioning on config change only** — lifecycle transitions do NOT bump
  `config_version`. Each version row contains a full snapshot (not a diff)
  so rollback is a simple swap.
- **Soft-delete via ARCHIVED** — no rows are removed. `list_records` /
  `GET /api/v1/agents` defaults to non-archived; clients must pass
  `status=archived` explicitly to see soft-deleted rows.
- **Name reuse after soft-delete** — the `(workspace_id, name)` unique
  index is partial (`WHERE status <> 'archived'`), so archiving an agent
  frees the name for a fresh registration.

## Public Surface
Re-exported from `__init__.py`: `AgentRegistryService`, `AgentPersistence`,
`AgentRecord`, `AgentConfigVersion`, `AgentStatus`, `AgentNotFoundError`,
`AgentNameConflictError`.
