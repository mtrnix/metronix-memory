# Metatron Core API Documentation

This document describes all API endpoints available in Metatron Core.

Base URL: `http://localhost:8000`

## Table of Contents

- [Health Checks](#health-checks)
- [Dashboard](#dashboard)
- [Workspaces](#workspaces)
- [Agents](#agents)
- [Connections](#connections)
- [Skills](#skills)
- [Files](#files)
- [Sync](#sync)
- [Query](#query)
- [Benchmarker](#benchmarker)

## Health Checks

### GET /health

Liveness check endpoint. Returns 200 if the service is running.

**Response:**

```json
{
  "status": "ok",
  "timestamp": "2026-02-11T10:30:00Z"
}
```

**Example:**

```bash
curl http://localhost:8000/health
```

### GET /ready

Readiness check endpoint. Verifies all required services are available.

**Response:**

```json
{
  "status": "ready",
  "services": {
    "database": "ok",
    "qdrant": "ok",
    "neo4j": "ok",
    "ollama": "ok"
  },
  "timestamp": "2026-02-11T10:30:00Z"
}
```

**Example:**

```bash
curl http://localhost:8000/ready
```

## Dashboard

### GET /api/v1/dashboard/overview

Get overview KPI metrics for the dashboard.

**Query Parameters:**

- `workspace_id` (string, required) — Workspace ID

**Response:**

```json
{
  "documents": 12483,
  "jira_issues": 841,
  "active_connectors": 3,
  "last_upload": "2026-03-02T09:12:00Z"
}
```

**Response Fields:**

- `documents` — Total number of documents in the workspace
- `jira_issues` — Total number of Jira issues synced
- `active_connectors` — Number of active data source connections
- `last_upload` — ISO 8601 timestamp of the last document upload, or `null` if no uploads yet

**Status Codes:**

- `200 OK` — Success
- `404 Not Found` — Workspace not found
- `422 Unprocessable Entity` — Missing or invalid workspace_id parameter

**Example:**

```bash
curl "http://localhost:8000/api/v1/dashboard/overview?workspace_id=550e8400-e29b-41d4-a716-446655440000"
```

**Notes:**

- If PostgreSQL is unavailable, `active_connectors` will return `0` (graceful degradation)
- Frontend should convert `last_upload` to relative time (e.g., "2h ago") using `Intl.RelativeTimeFormat`

### GET /api/v1/dashboard/sync-history

Get recent synchronization history for the dashboard.

**Query Parameters:**

- `workspace_id` (string, required) — Workspace ID
- `limit` (integer, optional) — Maximum number of records to return (default: 10, min: 1, max: 100)

**Response:**

```json
{
  "items": [
    {
      "id": "sync_1",
      "source": "confluence",
      "title": "Confluence Sync",
      "started": "2026-03-02T08:45:12Z",
      "duration_ms": 1240.5,
      "records": 18,
      "status": "success"
    },
    {
      "id": "sync_2",
      "source": "jira",
      "title": "Jira Sync",
      "started": "2026-03-02T07:30:00Z",
      "duration_ms": 890.2,
      "records": 12,
      "status": "partial"
    }
  ]
}
```

**Response Fields:**

- `id` — Unique sync log ID
- `source` — Connector type (e.g., "confluence", "jira", "notion")
- `title` — Human-readable sync source name
- `started` — ISO 8601 timestamp when sync started
- `duration_ms` — Sync duration in milliseconds
- `records` — Number of chunks created in Qdrant
- `status` — Sync status: "success", "partial", or "failed"

**Status Codes:**

- `200 OK` — Success
- `404 Not Found` — Workspace not found
- `422 Unprocessable Entity` — Invalid parameters

**Example:**

```bash
curl "http://localhost:8000/api/v1/dashboard/sync-history?workspace_id=550e8400-e29b-41d4-a716-446655440000&limit=10"
```

**Notes:**

- Results are sorted by `started` timestamp in descending order (newest first)
- If PostgreSQL is unavailable, returns empty array (graceful degradation)

### GET /api/v1/dashboard/ingestion-errors

Get recent ingestion errors for the dashboard.

**Query Parameters:**

- `workspace_id` (string, required) — Workspace ID
- `limit` (integer, optional) — Maximum number of error records to return (default: 20, min: 1, max: 100)

**Response:**

```json
{
  "total": 14,
  "items": [
    {
      "source": "confluence",
      "record": "page_id:12345 — Migration Guide",
      "error": "Qdrant timeout after 30s",
      "time": "2026-03-02T07:30:00Z",
      "severity": "warning"
    },
    {
      "source": "jira",
      "record": "Jira Sync",
      "error": "Connection refused",
      "time": "2026-03-02T06:15:00Z",
      "severity": "critical"
    }
  ]
}
```

**Response Fields:**

- `total` — Total number of errors in the workspace
- `items` — Array of error records (limited by `limit` parameter)
  - `source` — Connector type (e.g., "confluence", "jira", "notion")
  - `record` — Human-readable identifier of the failed sync
  - `error` — Error message (truncated to 200 characters)
  - `time` — ISO 8601 timestamp when error occurred
  - `severity` — Error severity: "critical" (failed), "warning" (partial), or "info"

**Status Codes:**

- `200 OK` — Success
- `404 Not Found` — Workspace not found
- `422 Unprocessable Entity` — Invalid parameters

**Example:**

```bash
curl "http://localhost:8000/api/v1/dashboard/ingestion-errors?workspace_id=550e8400-e29b-41d4-a716-446655440000&limit=20"
```

**Notes:**

- Only returns sync logs where `status != 'success'`
- Results are sorted by `time` timestamp in descending order (newest first)
- If PostgreSQL is unavailable, returns `{total: 0, items: []}` (graceful degradation)
- Error messages are extracted from the `errors` JSONB field (first error in array)

### GET /api/v1/dashboard/query-trend

Get query volume trend over time for the dashboard.

**Query Parameters:**

- `workspace_id` (string, required) — Workspace ID
- `days` (integer, optional) — Number of days to look back (default: 30, min: 1, max: 365)

**Response:**

```json
{
  "labels": ["2026-02-01", "2026-02-02", "2026-02-03"],
  "values": [124, 98, 156]
}
```

**Response Fields:**

- `labels` — Array of date strings in ISO 8601 format (YYYY-MM-DD)
- `values` — Array of query counts for each date (same length as `labels`)

**Status Codes:**

- `200 OK` — Success
- `404 Not Found` — Workspace not found
- `422 Unprocessable Entity` — Invalid parameters

**Example:**

```bash
curl "http://localhost:8000/api/v1/dashboard/query-trend?workspace_id=550e8400-e29b-41d4-a716-446655440000&days=30"
```

**Notes:**

- Aggregates data from `query_traces` table by date
- Missing dates (days with no queries) are filled with 0
- Results are sorted chronologically (oldest to newest)
- If PostgreSQL is unavailable, returns `{labels: [], values: []}` (graceful degradation)
- Date range is calculated as: `[today - days + 1, today]`

### GET /api/v1/dashboard/graph-stats

Get knowledge graph statistics for the dashboard.

**Query Parameters:**

- `workspace_id` (string, required) — Workspace ID

**Response:**

```json
{
  "total_nodes": 89200,
  "total_edges": 142800,
  "orphan_nodes": 47,
  "orphan_list": [
    {
      "id": "node_123",
      "label": "Entity",
      "name": "Deprecated API v1"
    }
  ],
  "lineage": {
    "raw_documents": 24831,
    "chunks": 412000,
    "graph_nodes": 89200
  }
}
```

**Response Fields:**

- `total_nodes` — Total number of nodes in the knowledge graph
- `total_edges` — Total number of relationships between nodes
- `orphan_nodes` — Count of nodes without any relationships
- `orphan_list` — Array of orphan node details (limited to 100)
  - `id` — Internal node ID
  - `label` — Node type/label (e.g., "Entity", "Document")
  - `name` — Node name (fallback: title, id, or "Unknown")
- `lineage` — Data processing pipeline statistics
  - `raw_documents` — Number of source documents ingested
  - `chunks` — Number of text chunks created
  - `graph_nodes` — Number of nodes in knowledge graph (same as `total_nodes`)

**Status Codes:**

- `200 OK` — Success
- `404 Not Found` — Workspace not found
- `422 Unprocessable Entity` — Missing or invalid workspace_id parameter

**Example:**

```bash
curl "http://localhost:8000/api/v1/dashboard/graph-stats?workspace_id=550e8400-e29b-41d4-a716-446655440000"
```

**Notes:**

- Data is retrieved from Neo4j (graph stats) and Qdrant (document/chunk counts)
- Orphan nodes are nodes without any relationships: `MATCH (n) WHERE NOT (n)--()`
- Edge count is divided by 2 for undirected relationships
- If Neo4j or Qdrant is unavailable, returns zeros (graceful degradation)
- Orphan list is limited to 100 nodes for performance

## Workspaces

### POST /api/v1/workspaces

Create a new workspace.

**Request Body:**

```json
{
  "name": "My Workspace",
  "description": "Optional workspace description"
}
```

**Response:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Workspace",
  "description": "Optional workspace description",
  "created_at": "2026-02-11T10:30:00Z",
  "updated_at": "2026-02-11T10:30:00Z"
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/workspaces \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Workspace",
    "description": "Optional workspace description"
  }'
```

### GET /api/v1/workspaces

List all workspaces.

**Response:**

```json
{
  "workspaces": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "My Workspace",
      "description": "Optional workspace description",
      "created_at": "2026-02-11T10:30:00Z",
      "updated_at": "2026-02-11T10:30:00Z"
    }
  ],
  "total": 1
}
```

**Example:**

```bash
curl http://localhost:8000/api/v1/workspaces
```

### GET /api/v1/workspaces/{id}

Get a specific workspace by ID.

**Response:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My Workspace",
  "description": "Optional workspace description",
  "created_at": "2026-02-11T10:30:00Z",
  "updated_at": "2026-02-11T10:30:00Z"
}
```

**Example:**

```bash
curl http://localhost:8000/api/v1/workspaces/550e8400-e29b-41d4-a716-446655440000
```

## Agents

Agent Registry (WS4, MTRNIX-270). First-class identity primitive for external
agent runtimes. Workspace is derived from the authenticated user — never from
request body or query string.

**RBAC:**
- `require_viewer` — reads (`GET /`, `GET /{id}`, `GET /{id}/versions`)
- `require_editor` — writes, lifecycle transitions, soft-delete

**Status transitions:** `stopped` (default on create) → `active | paused | stopped`
via lifecycle endpoints. `archived` via `DELETE`. Lifecycle transitions do NOT
bump `config_version`; only `PUT /{id}` does.

### POST /api/v1/agents

Create a new agent. Returns 201 with the full record.

**Request Body:**

```json
{
  "name": "Trader",
  "model": "claude-sonnet-4-6",
  "capabilities": ["trade", "analyze"],
  "tools": ["search", "memory_store"],
  "memory_bindings": {"scopes": ["PER_AGENT", "SESSION"]},
  "budget": {"tokens_per_day": 100000, "cost_usd_month": 50}
}
```

`capabilities`, `tools`, `memory_bindings`, `budget` are optional. `memory_bindings`
and `budget` are opaque JSONB (enforcement deferred). Max 32 KiB serialized for
each.

**Response:**

```json
{
  "id": "3f1c4b2e5d6a4f9e8b7c6d5e4f3a2b1c",
  "workspace_id": "ws-acme",
  "name": "Trader",
  "status": "stopped",
  "model": "claude-sonnet-4-6",
  "capabilities": ["trade", "analyze"],
  "tools": ["search", "memory_store"],
  "memory_bindings": {"scopes": ["PER_AGENT", "SESSION"]},
  "budget": {"tokens_per_day": 100000, "cost_usd_month": 50},
  "config_version": 1,
  "current_config": {
    "name": "Trader", "model": "claude-sonnet-4-6",
    "capabilities": ["trade", "analyze"], "tools": ["search", "memory_store"],
    "memory_bindings": {"scopes": ["PER_AGENT", "SESSION"]},
    "budget": {"tokens_per_day": 100000, "cost_usd_month": 50}
  },
  "created_by": "user-42",
  "created_at": "2026-04-21T10:30:00Z",
  "updated_at": "2026-04-21T10:30:00Z"
}
```

**Errors:** 409 if `name` is already used in the workspace.

### GET /api/v1/agents

List agents in the current workspace.

**Query params:**

| Name | Type | Default | Notes |
|---|---|---|---|
| `status` | enum | — | `active \| paused \| stopped \| archived` |
| `name_prefix` | string | — | Prefix filter, 1..128 chars, `%` and `_` are escaped |
| `limit` | int | 50 | 1..200 |
| `offset` | int | 0 | 0..10000 |

**Response:**

```json
{
  "agents": [ { /* AgentResponse */ } ],
  "count": 1,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

### GET /api/v1/agents/{id}

Fetch a single agent, including `current_config`.

**Errors:** 404 if not found in this workspace.

### PUT /api/v1/agents/{id}

Partial update. Any subset of mutable fields; at least one field required (else
422). Merges with existing state, recomputes the snapshot, bumps `config_version`
by one, and appends a new row to the version history — all in a single PG
transaction (`SELECT … FOR UPDATE`).

**Request Body:**

```json
{
  "model": "claude-opus-4-7",
  "capabilities": ["trade", "analyze", "report"]
}
```

**Response:** updated `AgentResponse` with `config_version` incremented.

**Errors:** 404 if not found; 409 if new name collides with another agent.

### DELETE /api/v1/agents/{id}

Soft-delete — flips `status` to `archived`. No rows are removed; version history
stays intact. Returns 204.

**Errors:** 404 if not found.

### POST /api/v1/agents/{id}/start

Set `status` to `active`. Returns 200 with the updated record. Version not bumped.

### POST /api/v1/agents/{id}/stop

Set `status` to `stopped`. Returns 200 with the updated record. Version not bumped.

### POST /api/v1/agents/{id}/pause

Set `status` to `paused`. Returns 200 with the updated record. Version not bumped.

### GET /api/v1/agents/{id}/versions

List historical config versions for an agent, newest first.

**Query params:** `limit` (default 50, max 200), `offset` (default 0, max 10000).

**Response:**

```json
{
  "versions": [
    {
      "agent_id": "3f1c4b2e5d6a4f9e8b7c6d5e4f3a2b1c",
      "version": 2,
      "config": { "name": "Trader", "model": "claude-opus-4-7", "...": "..." },
      "changed_by": "user-42",
      "changed_at": "2026-04-21T11:00:00Z"
    }
  ],
  "count": 2,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

**Errors:** 404 if the agent does not exist in this workspace.

## Connections

### POST /api/v1/connections

Create a new data source connection. Configuration is automatically encrypted.

**Request Body:**

```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_type": "slack",
  "name": "My Slack Connection",
  "config": {
    "token": "xoxb-your-slack-token",
    "channels": ["general", "engineering"]
  }
}
```

**Response:**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_type": "slack",
  "name": "My Slack Connection",
  "status": "active",
  "created_at": "2026-02-11T10:30:00Z",
  "updated_at": "2026-02-11T10:30:00Z",
  "last_sync_at": null
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/connections \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
    "source_type": "slack",
    "name": "My Slack Connection",
    "config": {
      "token": "xoxb-your-slack-token",
      "channels": ["general", "engineering"]
    }
  }'
```

### GET /api/v1/connections

List connections, optionally filtered by workspace.

**Query Parameters:**

- `workspace_id` (optional): Filter by workspace ID

**Response:**

```json
{
  "connections": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
      "source_type": "slack",
      "name": "My Slack Connection",
      "status": "active",
      "created_at": "2026-02-11T10:30:00Z",
      "updated_at": "2026-02-11T10:30:00Z",
      "last_sync_at": "2026-02-11T11:00:00Z"
    }
  ],
  "total": 1
}
```

**Example:**

```bash
curl "http://localhost:8000/api/v1/connections?workspace_id=550e8400-e29b-41d4-a716-446655440000"
```

### POST /api/v1/connections/{id}/sync

Trigger a sync for a specific connection.

**Response:**

```json
{
  "connection_id": "660e8400-e29b-41d4-a716-446655440001",
  "sync_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "queued",
  "started_at": "2026-02-11T11:00:00Z"
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/connections/660e8400-e29b-41d4-a716-446655440001/sync
```

### GET /api/v1/connections/{id}/reveal-secrets

Get a single connection with decrypted secret values. Requires editor role or higher.

**Query Parameters:**

- `workspace_id` (optional): Workspace ID

**Response:**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "connector_type": "jira",
  "name": "My Jira Connection",
  "config": {
    "url": "https://acme.atlassian.net/",
    "username": "bot@acme.com",
    "api_token": "ATATT3xFfGF0...",
    "project_key": "PROJ"
  },
  "status": "active",
  "enabled": true,
  "error_message": null,
  "last_synced_at": "2026-02-11T11:00:00Z",
  "created_at": "2026-02-11T10:30:00Z",
  "updated_at": null
}
```

**Status Codes:**

- `200 OK` — Success
- `403 Forbidden` — Viewer role (requires editor or admin)
- `404 Not Found` — Connection not found or workspace mismatch

**Example:**

```bash
curl "http://localhost:8000/api/v1/connections/660e8400-e29b-41d4-a716-446655440001/reveal-secrets?workspace_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### DELETE /api/v1/connections/{id}

Delete a connection and all associated data.

**Response:**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "deleted",
  "deleted_at": "2026-02-11T11:30:00Z"
}
```

**Example:**

```bash
curl -X DELETE http://localhost:8000/api/v1/connections/660e8400-e29b-41d4-a716-446655440001
```

## Skills

### GET /api/v1/skills

List all available skills.

**Response:**

```json
{
  "skills": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440003",
      "name": "document_search",
      "description": "Search through documents using semantic search",
      "type": "query",
      "config": {
        "enabled": true
      },
      "created_at": "2026-02-11T10:00:00Z",
      "updated_at": "2026-02-11T10:00:00Z"
    }
  ],
  "total": 1
}
```

**Example:**

```bash
curl http://localhost:8000/api/v1/skills
```

### POST /api/v1/skills

Create a new skill.

**Request Body:**

```json
{
  "name": "custom_skill",
  "description": "A custom skill for specific use case",
  "type": "query",
  "config": {
    "enabled": true,
    "parameters": {
      "max_results": 10
    }
  }
}
```

**Response:**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "name": "custom_skill",
  "description": "A custom skill for specific use case",
  "type": "query",
  "config": {
    "enabled": true,
    "parameters": {
      "max_results": 10
    }
  },
  "created_at": "2026-02-11T10:00:00Z",
  "updated_at": "2026-02-11T10:00:00Z"
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/skills \
  -H "Content-Type: application/json" \
  -d '{
    "name": "custom_skill",
    "description": "A custom skill for specific use case",
    "type": "query",
    "config": {
      "enabled": true,
      "parameters": {
        "max_results": 10
      }
    }
  }'
```

### GET /api/v1/skills/{id}

Get a specific skill by ID.

**Response:**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "name": "custom_skill",
  "description": "A custom skill for specific use case",
  "type": "query",
  "config": {
    "enabled": true,
    "parameters": {
      "max_results": 10
    }
  },
  "created_at": "2026-02-11T10:00:00Z",
  "updated_at": "2026-02-11T10:00:00Z"
}
```

**Example:**

```bash
curl http://localhost:8000/api/v1/skills/880e8400-e29b-41d4-a716-446655440003
```

### PUT /api/v1/skills/{id}

Update an existing skill.

**Request Body:**

```json
{
  "description": "Updated description",
  "config": {
    "enabled": false,
    "parameters": {
      "max_results": 20
    }
  }
}
```

**Response:**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "name": "custom_skill",
  "description": "Updated description",
  "type": "query",
  "config": {
    "enabled": false,
    "parameters": {
      "max_results": 20
    }
  },
  "created_at": "2026-02-11T10:00:00Z",
  "updated_at": "2026-02-11T12:00:00Z"
}
```

**Example:**

```bash
curl -X PUT http://localhost:8000/api/v1/skills/880e8400-e29b-41d4-a716-446655440003 \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Updated description",
    "config": {
      "enabled": false,
      "parameters": {
        "max_results": 20
      }
    }
  }'
```

### DELETE /api/v1/skills/{id}

Delete a skill.

**Response:**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "status": "deleted",
  "deleted_at": "2026-02-11T12:30:00Z"
}
```

**Example:**

```bash
curl -X DELETE http://localhost:8000/api/v1/skills/880e8400-e29b-41d4-a716-446655440003
```

## Files

### POST /api/v1/files

Upload a file to a workspace.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

**Request:**

Multipart form data with file field.

**Response:**

```json
{
  "id": "990e8400-e29b-41d4-a716-446655440004",
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "size": 1048576,
  "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "uploaded_at": "2026-02-11T13:00:00Z"
}
```

**Example:**

```bash
curl -X POST "http://localhost:8000/api/v1/files?workspace_id=550e8400-e29b-41d4-a716-446655440000" \
  -F "file=@/path/to/document.pdf"
```

### GET /api/v1/files

List files in a workspace.

**Query Parameters:**

- `workspace_id` (required): Workspace ID
- `limit` (optional): Number of results (default: 50)
- `offset` (optional): Pagination offset (default: 0)

**Response:**

```json
{
  "files": [
    {
      "id": "990e8400-e29b-41d4-a716-446655440004",
      "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
      "filename": "document.pdf",
      "content_type": "application/pdf",
      "size": 1048576,
      "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "uploaded_at": "2026-02-11T13:00:00Z"
    }
  ],
  "total": 1
}
```

**Example:**

```bash
curl "http://localhost:8000/api/v1/files?workspace_id=550e8400-e29b-41d4-a716-446655440000"
```

### GET /api/v1/files/{id}/verify

Verify file integrity by checking its checksum.

**Response:**

```json
{
  "id": "990e8400-e29b-41d4-a716-446655440004",
  "filename": "document.pdf",
  "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "verified": true,
  "verified_at": "2026-02-11T14:00:00Z"
}
```

**Example:**

```bash
curl http://localhost:8000/api/v1/files/990e8400-e29b-41d4-a716-446655440004/verify
```

### GET /api/v1/files/{id}/download

Download an uploaded file by its ID.

**Query Parameters:**

- `workspace_id` (required): Workspace the file belongs to

**Response:** Raw file content with appropriate `Content-Type` header.

**Headers:**

- `Content-Disposition: inline; filename="original_name.pdf"`

**Error Responses:**

- `404 Not Found` — File or workspace not found

**Example:**

```bash
curl "http://localhost:8000/api/v1/files/990e8400-e29b-41d4-a716-446655440004/download?workspace_id=550e8400-e29b-41d4-a716-446655440000"
```

## Sync

### GET /api/v1/sync/status

Get sync status for all connections in a workspace.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

**Response:**

```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "syncs": [
    {
      "connection_id": "660e8400-e29b-41d4-a716-446655440001",
      "connection_name": "My Slack Connection",
      "sync_id": "770e8400-e29b-41d4-a716-446655440002",
      "status": "completed",
      "started_at": "2026-02-11T11:00:00Z",
      "completed_at": "2026-02-11T11:05:00Z",
      "items_synced": 1523,
      "errors": 0
    }
  ]
}
```

**Example:**

```bash
curl "http://localhost:8000/api/v1/sync/status?workspace_id=550e8400-e29b-41d4-a716-446655440000"
```

### GET /api/v1/sync/logs

Get sync logs for all connections in a workspace.

**Query Parameters:**

- `workspace_id` (required): Workspace ID
- `limit` (optional): Number of log entries (default: 100)
- `offset` (optional): Pagination offset (default: 0)

**Response:**

```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "logs": [
    {
      "sync_id": "770e8400-e29b-41d4-a716-446655440002",
      "connection_id": "660e8400-e29b-41d4-a716-446655440001",
      "timestamp": "2026-02-11T11:00:00Z",
      "level": "info",
      "message": "Starting sync for connection My Slack Connection"
    },
    {
      "sync_id": "770e8400-e29b-41d4-a716-446655440002",
      "connection_id": "660e8400-e29b-41d4-a716-446655440001",
      "timestamp": "2026-02-11T11:05:00Z",
      "level": "info",
      "message": "Sync completed successfully: 1523 items synced"
    }
  ],
  "total": 2
}
```

**Example:**

```bash
curl "http://localhost:8000/api/v1/sync/logs?workspace_id=550e8400-e29b-41d4-a716-446655440000&limit=100"
```

## Query

### POST /api/v1/query/trace

Benchmarker endpoint for tracing query execution. Returns detailed execution metrics.

**Request Body:**

```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "query": "What were the main topics discussed in the engineering channel last week?",
  "options": {
    "max_results": 10,
    "include_sources": true
  }
}
```

**Response:**

```json
{
  "query_id": "aa0e8400-e29b-41d4-a716-446655440005",
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "query": "What were the main topics discussed in the engineering channel last week?",
  "answer": "Based on the messages in the engineering channel, the main topics discussed last week were: 1) Database migration issues, 2) New feature planning for Q2, 3) Performance optimization.",
  "sources": [
    {
      "id": "bb0e8400-e29b-41d4-a716-446655440006",
      "content": "We need to address the database migration issues...",
      "source_type": "slack",
      "relevance_score": 0.92,
      "metadata": {
        "channel": "engineering",
        "author": "john.doe",
        "timestamp": "2026-02-05T14:30:00Z"
      }
    }
  ],
  "trace": {
    "total_duration_ms": 342,
    "embedding_duration_ms": 45,
    "vector_search_duration_ms": 78,
    "graph_query_duration_ms": 52,
    "llm_duration_ms": 167
  },
  "timestamp": "2026-02-11T15:00:00Z"
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/api/v1/query/trace \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "What were the main topics discussed in the engineering channel last week?",
    "options": {
      "max_results": 10,
      "include_sources": true
    }
  }'
```

## Benchmarker

Automated RAG quality evaluation. All endpoints are prefixed with `/api/v1/benchmarker`.

### POST /api/v1/benchmarker/generate

Generate benchmark questions from workspace documents using BenchmarkQED.

**Request Body:**

```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "num_questions": 10,
  "source": "confluence",
  "num_clusters": null
}
```

**Response:**

```json
{
  "id": "uuid",
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Generated (confluence)",
  "source": "confluence",
  "description": "Auto-generated from confluence documents",
  "tokens_used": 1500,
  "question_count": 10,
  "created_at": "2026-02-20T10:00:00Z",
  "questions": [
    {
      "id": "q1",
      "text": "What is the authentication strategy?",
      "question_type": "data_local",
      "references": ["ref1"],
      "attributes": { "..." : "..." }
    }
  ]
}
```

### POST /api/v1/benchmarker/run-tests

Run benchmark tests against the RAG pipeline with 6 metrics (correctness, answer relevancy, faithfulness, context precision, context recall, confidence).

**Request Body:**

```json
{
  "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
  "benchmark_set_id": "uuid",
  "name": "Test Run 1",
  "description": "Optional description"
}
```

**Response:**

```json
{
  "id": "uuid",
  "benchmark_set_id": "uuid",
  "name": "Test Run 1",
  "total_tests": 10,
  "created_at": "2026-02-20T10:05:00Z",
  "avg_correctness": 0.82,
  "avg_answer_relevancy": 0.75,
  "avg_faithfulness": 0.88,
  "avg_context_precision": 0.70,
  "avg_context_recall": 0.65,
  "avg_confidence": 1.0,
  "results": [
    {
      "id": "uuid",
      "question": { "text": "What is X?", "..." : "..." },
      "actual_answer": "X is ...",
      "correctness": 0.85,
      "answer_relevancy": 0.78,
      "faithfulness": 0.90,
      "context_precision": 0.72,
      "context_recall": 0.68,
      "confidence": 1.0,
      "claim_scores": [{"claim": "c1", "score": 80}]
    }
  ]
}
```

### GET /api/v1/benchmarker/benchmarks

List all benchmark sets for a workspace.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

**Response:**

```json
{
  "benchmarks": [
    {
      "id": "uuid",
      "workspace_id": "uuid",
      "name": "Generated (confluence)",
      "description": "Auto-generated",
      "source": "confluence",
      "question_count": 10,
      "tokens_used": 1500,
      "created_at": "2026-02-20T10:00:00Z"
    }
  ],
  "count": 1
}
```

### GET /api/v1/benchmarker/benchmarks/{id}

Get a benchmark set with all its questions.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

**Response:**

```json
{
  "benchmark": {
    "id": "uuid",
    "name": "Generated (confluence)",
    "source": "confluence",
    "question_count": 10,
    "created_at": "2026-02-20T10:00:00Z"
  },
  "questions": [
    {
      "id": "q1",
      "text": "What is X?",
      "question_type": "data_local",
      "references": ["ref1"],
      "attributes": { "..." : "..." }
    }
  ]
}
```

### POST /api/v1/benchmarker/benchmarks

Create (or upsert) a benchmark set with questions.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

**Request Body:**

```json
{
  "name": "My Benchmark",
  "source": "jira",
  "questions": [
    {
      "text": "What is X?",
      "question_type": "data_local",
      "attributes": { "input_question": "What is X?", "reference_coverage": 0.5, "..." : "..." }
    }
  ],
  "tokens_used": 500
}
```

**Response:**

```json
{
  "success": true,
  "id": "uuid",
  "name": "My Benchmark",
  "source": "jira",
  "question_count": 1,
  "created_at": "2026-02-20T10:00:00Z"
}
```

### DELETE /api/v1/benchmarker/benchmarks/{id}

Delete a benchmark set and all its questions.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

### POST /api/v1/benchmarker/benchmarks/{id}/clone

Clone a benchmark set with all its questions.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

**Response:**

```json
{
  "id": "new-uuid",
  "name": "Generated (confluence)",
  "question_count": 10,
  "created_at": "2026-02-20T10:00:00Z"
}
```

### GET /api/v1/benchmarker/test-runs

List all test runs for a workspace.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

**Response:**

```json
{
  "test_runs": [
    {
      "id": "uuid",
      "benchmark_set_id": "uuid",
      "name": "Test Run 1",
      "total_tests": 10,
      "created_at": "2026-02-20T10:05:00Z",
      "avg_correctness": 0.82,
      "avg_answer_relevancy": 0.75,
      "avg_faithfulness": 0.88,
      "avg_context_precision": 0.70,
      "avg_context_recall": 0.65,
      "avg_confidence": 1.0
    }
  ],
  "count": 1
}
```

### GET /api/v1/benchmarker/test-runs/{id}

Get a test run with all its results.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

### POST /api/v1/benchmarker/test-runs

Save a test run with pre-computed results.

**Request Body:**

```json
{
  "benchmark_set_id": "uuid",
  "name": "Run 1",
  "results": [
    {
      "actual_answer": "Answer text",
      "correctness": 0.85,
      "answer_relevancy": 0.78,
      "faithfulness": 0.90,
      "context_precision": 0.72,
      "context_recall": 0.68,
      "confidence": 1.0
    }
  ]
}
```

### DELETE /api/v1/benchmarker/test-runs/{id}

Delete a test run and all its results.

**Query Parameters:**

- `workspace_id` (required): Workspace ID

## OpenAI-Compatible API (Open WebUI Integration)

OpenAI-compatible endpoints for connecting Open WebUI or any OpenAI-compatible client to Metatron.

**Authentication:** `Authorization: Bearer <personal API key (mtk_...)>` or `Bearer <METATRON_OPENAI_COMPAT_KEY>` (Home scenario fallback)

**Error format:** `{"error": {"message": "...", "type": "invalid_request_error"}}`

### GET /v1/models

List available models. Each workspace is exposed as a separate model.

**Response:**

```json
{
  "object": "list",
  "data": [
    {
      "id": "metatron-rag-MTRNIX",
      "object": "model",
      "created": 1710000000,
      "owned_by": "metatron"
    }
  ]
}
```

**Example:**

```bash
curl -H "Authorization: Bearer YOUR_KEY" http://localhost:8000/v1/models
```

### POST /v1/chat/completions

Chat completions in OpenAI format. Calls the Metatron hybrid search pipeline internally.

**Request Body:**

```json
{
  "model": "metatron-rag-MTRNIX",
  "messages": [
    {"role": "user", "content": "What tasks are in backlog?"}
  ],
  "stream": true,
  "user": "optional-user-id"
}
```

Fields `temperature`, `max_tokens`, `top_p` etc. are accepted but ignored — LLM parameters are controlled by the search pipeline.

**Streaming Response (SSE):**

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{"content":"The backlog contains..."},"finish_reason":null}]}
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

**Non-Streaming Response:**

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "metatron-rag-MTRNIX",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Answer with sources..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

**Example:**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "metatron-rag-MTRNIX", "messages": [{"role": "user", "content": "Hello"}], "stream": false}'
```

### Open WebUI Setup

**Home (single user, no auth):**
1. `docker compose -f docker-compose.full.yml --profile openwebui up`
2. Open `http://localhost:3080` — no login required
3. Global connection pre-configured via env vars

**Bundled (multi-user):**
1. Set `METATRON_OPENWEBUI_URL` and `METATRON_OPENWEBUI_METATRON_URL` in Metatron env
2. Open WebUI must have `WEBUI_AUTH=true`, `ENABLE_DIRECT_CONNECTIONS=true`
3. Do NOT set `OPENAI_API_BASE_URL`/`OPENAI_API_KEY` in Open WebUI (no global connection)
4. Create users in Metatron — they auto-sync to Open WebUI with personal API keys
5. OWUI admin password = Metatron `AUTH_PASSWORD` (default: `metatron`)

**External (existing Open WebUI):**
1. Open WebUI must have `ENABLE_DIRECT_CONNECTIONS=true` (mandatory for security)
2. Import users: `POST /api/v1/admin/import-openwebui-users` with OWUI URL + admin credentials
3. Download JSON with generated Metatron passwords and API keys
4. Each user sets Direct Connection in Open WebUI: Settings → Connections → URL + personal API key

### POST /api/v1/admin/import-openwebui-users

Import users from an external Open WebUI instance. Admin only.

**Request Body:**
```json
{
  "owui_url": "http://openwebui.company.com",
  "admin_email": "admin@company.com",
  "admin_password": "password"
}
```

**Response:**
```json
{
  "imported": [
    {"email": "user@company.com", "name": "User", "role": "viewer", "metatron_password": "...", "api_key": "mtk_..."}
  ],
  "skipped": 0,
  "already_existed": 1,
  "total_in_owui": 5
}
```

Role mapping: OWUI admin → Metatron admin, OWUI user → Metatron viewer, OWUI pending → skipped.

### Personal API Key Management

- `POST /api/v1/users/{user_id}/api-keys` — create key (returns raw key once, 201)
- `GET /api/v1/users/{user_id}/api-keys` — list keys (prefix + label, no secrets)
- `DELETE /api/v1/users/{user_id}/api-keys/{key_prefix}` — revoke key (204)

## Error Responses

All endpoints may return error responses in the following format:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Workspace not found",
    "details": {
      "workspace_id": "550e8400-e29b-41d4-a716-446655440000"
    }
  }
}
```

Common HTTP status codes:

- `200 OK` - Request succeeded
- `201 Created` - Resource created successfully
- `400 Bad Request` - Invalid request parameters
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

## Rate Limiting

API requests are rate-limited to prevent abuse:

- 100 requests per minute per IP address
- 1000 requests per hour per IP address

Rate limit headers are included in responses:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1644583200
```

## Authentication

Currently, the API does not require authentication for local development. In production environments, use API keys:

```bash
curl http://localhost:8000/api/v1/workspaces \
  -H "Authorization: Bearer YOUR_API_KEY"
```
