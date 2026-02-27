# Metatron Core API Documentation

This document describes all API endpoints available in Metatron Core.

Base URL: `http://localhost:8000`

## Table of Contents

- [Health Checks](#health-checks)
- [Workspaces](#workspaces)
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
    "memgraph": "ok",
    "ollama": "ok"
  },
  "timestamp": "2026-02-11T10:30:00Z"
}
```

**Example:**

```bash
curl http://localhost:8000/ready
```

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
