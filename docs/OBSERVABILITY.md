# Observability

## Overview

Metatron provides detailed observability into query processing, sync operations, and system health through structured logging, query traces, and health check endpoints.

## Query Trace Format

Every query in Metatron is broken down into 7 distinct steps, each with timing and metadata. This enables performance analysis and debugging of the retrieval pipeline.

### Trace Structure

```json
{
  "query": "user's search query",
  "workspace_id": "uuid",
  "total_duration_ms": 450,
  "steps": [
    {
      "name": "embed_query",
      "duration_ms": 120,
      "metadata": {
        "model": "all-MiniLM-L6-v2",
        "embedding_dim": 384
      }
    },
    {
      "name": "dense_search",
      "duration_ms": 80,
      "metadata": {
        "collection": "workspace-uuid",
        "limit": 100,
        "results_count": 87
      }
    },
    {
      "name": "sparse_search",
      "duration_ms": 60,
      "metadata": {
        "limit": 100,
        "results_count": 92
      }
    },
    {
      "name": "rrf_fusion",
      "duration_ms": 15,
      "metadata": {
        "dense_count": 87,
        "sparse_count": 92,
        "fused_count": 120,
        "k": 60
      }
    },
    {
      "name": "graph_enrichment",
      "duration_ms": 45,
      "metadata": {
        "related_chunks_added": 23,
        "graph_query_time_ms": 35
      }
    },
    {
      "name": "multi_factor_scoring",
      "duration_ms": 80,
      "metadata": {
        "signals": {
          "relevance": 0.85,
          "recency": 0.65,
          "authority": 0.75,
          "completeness": 0.90,
          "user_engagement": 0.70,
          "source_trust": 0.80
        },
        "top_score": 0.825
      }
    },
    {
      "name": "context_assembly",
      "duration_ms": 50,
      "metadata": {
        "chunks_selected": 15,
        "root_chunks_linked": 8,
        "total_context_tokens": 3200,
        "max_context_tokens": 4000
      }
    }
  ]
}
```

### Step Descriptions

#### 1. embed_query

Converts the user's query into a dense vector embedding.

**Metadata**:
- `model`: Embedding model name (e.g., `all-MiniLM-L6-v2`)
- `embedding_dim`: Dimension of the embedding vector (e.g., 384)

**Typical Duration**: 50-150ms

#### 2. dense_search

Performs vector similarity search in Qdrant using the query embedding.

**Metadata**:
- `collection`: Qdrant collection name (usually `workspace-{workspace_id}`)
- `limit`: Number of results requested from Qdrant
- `results_count`: Number of results actually returned

**Typical Duration**: 50-200ms (depends on collection size)

#### 3. sparse_search

Performs BM25-style keyword search using sparse vectors (TF-IDF).

**Metadata**:
- `limit`: Number of results requested
- `results_count`: Number of results returned

**Typical Duration**: 40-150ms

#### 4. rrf_fusion

Combines dense and sparse search results using Reciprocal Rank Fusion.

**Metadata**:
- `dense_count`: Number of results from dense search
- `sparse_count`: Number of results from sparse search
- `fused_count`: Total unique results after fusion
- `k`: RRF parameter (default: 60)

**Typical Duration**: 10-30ms

**Algorithm**: For each result, compute `score = sum(1 / (k + rank_i))` across both result lists.

#### 5. graph_enrichment

Fetches related chunks from the knowledge graph (parent/child relationships, citations).

**Metadata**:
- `related_chunks_added`: Number of additional chunks retrieved from graph
- `graph_query_time_ms`: Time spent querying Memgraph

**Typical Duration**: 30-100ms

**Cypher Query Example**:
```cypher
MATCH (c:Chunk)-[:RELATED_TO|:CITES]->(related:Chunk)
WHERE c.id IN $chunk_ids
RETURN DISTINCT related
```

#### 6. multi_factor_scoring

Scores each chunk using 6 signals and computes a weighted final score.

**Metadata**:
- `signals`: Map of signal name to weight/score
  - `relevance`: Vector similarity score (0-1)
  - `recency`: Document age score (newer is better)
  - `authority`: Source authority score (e.g., official docs > Slack messages)
  - `completeness`: Chunk completeness (root chunks > child chunks)
  - `user_engagement`: Historical user interactions (views, upvotes)
  - `source_trust`: Trustworthiness of the source (configured per workspace)
- `top_score`: Highest score among all chunks

**Typical Duration**: 50-150ms

**Scoring Formula**:
```
final_score = (
  0.40 * relevance +
  0.15 * recency +
  0.15 * authority +
  0.15 * completeness +
  0.10 * user_engagement +
  0.05 * source_trust
)
```

#### 7. context_assembly

Selects top chunks and assembles them into a context window for the LLM.

**Metadata**:
- `chunks_selected`: Number of chunks included in final context
- `root_chunks_linked`: Number of root chunks linked (for "show full document")
- `total_context_tokens`: Total tokens in assembled context
- `max_context_tokens`: Maximum allowed tokens (depends on LLM model)

**Typical Duration**: 30-100ms

**Strategy**:
1. Sort chunks by final score (descending)
2. Add chunks to context until token limit is reached
3. For each chunk, link its root chunk (if not already in context)
4. Format as Markdown with metadata headers

## Using the Benchmarker API

The benchmarker API exposes query traces for performance analysis.

### Endpoint

```
POST /api/v1/query/trace
```

### Request

```json
{
  "workspace_id": "uuid",
  "query": "What is our authentication strategy?"
}
```

### Response

Full trace object (see Trace Structure above).

### Example: cURL

```bash
curl -X POST http://localhost:8000/api/v1/query/trace \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "What is our authentication strategy?"
  }'
```

### Example: Python

```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/query/trace",
    headers={"Authorization": "Bearer YOUR_API_KEY"},
    json={
        "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
        "query": "What is our authentication strategy?"
    }
)

trace = response.json()
print(f"Total duration: {trace['total_duration_ms']}ms")
for step in trace["steps"]:
    print(f"  {step['name']}: {step['duration_ms']}ms")
```

### Use Cases

- **Performance Debugging**: Identify slow steps (e.g., graph_enrichment taking > 200ms)
- **Quality Analysis**: Review multi_factor_scoring signals to understand ranking
- **A/B Testing**: Compare traces with different ranking weights or fusion strategies
- **Monitoring**: Track P50/P95/P99 durations for each step over time

## Sync Logs

Every sync operation (via connectors) generates a structured log with results and errors.

### Log Format

```json
{
  "timestamp": "2026-02-11T10:30:00Z",
  "level": "info",
  "event": "sync_completed",
  "connection_id": "uuid",
  "workspace_id": "uuid",
  "connector_type": "confluence",
  "duration_seconds": 120,
  "documents_fetched": 450,
  "documents_indexed": 445,
  "errors": [
    {
      "document_id": "CONF-123",
      "error": "Indexing failed: chunking timeout",
      "timestamp": "2026-02-11T10:28:45Z"
    }
  ]
}
```

### Accessing Sync Logs

Sync logs are written to stdout (JSON format) and can be:

1. **Viewed in console**: `docker compose logs metatron-core`
2. **Shipped to logging service**: Configure a log collector (e.g., Fluentd, Logstash) to parse JSON logs
3. **Queried via API**: `GET /api/v1/connections/{connection_id}/sync-logs`

### Sync Log Fields

- `connection_id`: UUID of the connection that triggered the sync
- `connector_type`: Type of connector (e.g., `confluence`, `jira`)
- `documents_fetched`: Total documents retrieved from source
- `documents_indexed`: Documents successfully indexed (may be < fetched due to errors)
- `errors`: List of per-document errors with timestamps

### Example: Querying Sync Logs via API

```bash
curl http://localhost:8000/api/v1/connections/uuid/sync-logs \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Response:
```json
{
  "connection_id": "uuid",
  "syncs": [
    {
      "sync_id": "uuid",
      "started_at": "2026-02-11T10:00:00Z",
      "completed_at": "2026-02-11T10:02:00Z",
      "status": "completed",
      "documents_fetched": 450,
      "documents_indexed": 445,
      "errors_count": 5
    }
  ]
}
```

## Health Checks

Metatron exposes two health check endpoints.

### Liveness Probe

**Endpoint**: `GET /health`

**Purpose**: Check if the service is running.

**Response** (200 OK):
```json
{
  "status": "healthy"
}
```

**Use Case**: Kubernetes liveness probe to restart crashed pods.

### Readiness Probe

**Endpoint**: `GET /ready`

**Purpose**: Check if the service is ready to handle requests (all dependencies are available).

**Response** (200 OK):
```json
{
  "status": "ready",
  "dependencies": {
    "postgres": "healthy",
    "qdrant": "healthy",
    "memgraph": "healthy",
    "ollama": "healthy"
  }
}
```

**Response** (503 Service Unavailable):
```json
{
  "status": "not_ready",
  "dependencies": {
    "postgres": "healthy",
    "qdrant": "unhealthy",
    "memgraph": "healthy",
    "ollama": "healthy"
  }
}
```

**Use Case**: Kubernetes readiness probe to delay traffic until service is ready.

### Dependency Checks

The readiness probe performs the following checks:

- **postgres**: `SELECT 1` query
- **qdrant**: `GET /collections` API call
- **memgraph**: Cypher query `RETURN 1`
- **ollama**: `GET /api/tags` API call

If any dependency is unreachable, the service reports `not_ready`.

## Structured Logging

Metatron uses `structlog` for all logging. Logs are emitted in JSON format.

### Log Format

```json
{
  "timestamp": "2026-02-11T10:30:00Z",
  "level": "info",
  "event": "query_executed",
  "workspace_id": "uuid",
  "trace_id": "uuid",
  "duration_ms": 450,
  "query_length": 35,
  "results_count": 15
}
```

### Contextual Logging

Use `structlog.contextvars` to bind context to all logs within a request:

```python
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

logger = structlog.get_logger()

async def handle_query(query: str, workspace_id: str):
    bind_contextvars(
        workspace_id=workspace_id,
        trace_id=generate_trace_id()
    )

    logger.info("query_started", query_length=len(query))

    # All subsequent logs will include workspace_id and trace_id
    result = await execute_query(query)

    logger.info("query_completed", results_count=len(result))

    clear_contextvars()
```

### Log Levels

- `debug`: Verbose debugging info (disabled in production)
- `info`: Normal operational events (query executed, sync completed)
- `warning`: Non-critical issues (rate limit hit, retry triggered)
- `error`: Errors that need attention (connector failed, indexing error)
- `critical`: System-level failures (database unreachable, out of memory)

### Best Practices

1. **Never use print()**: Always use `logger.info()` or equivalent
2. **Structured fields**: Use keyword arguments, not string interpolation
   - Good: `logger.info("query_executed", duration_ms=450)`
   - Bad: `logger.info(f"Query took {duration_ms}ms")`
3. **Event names**: Use snake_case, past tense (e.g., `sync_completed`, `query_executed`)
4. **No secrets**: Never log API keys, tokens, or passwords
5. **Use context vars**: Bind `workspace_id` and `trace_id` for request tracing

## Metrics

Metatron maintains in-memory counters for key metrics. Future versions will export these to Prometheus.

### Available Metrics

```python
from src.observability.metrics import metrics

# Query metrics
metrics.increment("queries.executed")
metrics.increment("queries.failed")
metrics.observe("queries.duration_ms", 450)

# Sync metrics
metrics.increment("syncs.completed")
metrics.increment("syncs.failed")
metrics.observe("syncs.documents_indexed", 450)

# Connector metrics
metrics.increment("connectors.confluence.syncs")
metrics.increment("connectors.jira.syncs")
```

### Accessing Metrics

Currently, metrics are stored in memory and logged periodically:

```json
{
  "timestamp": "2026-02-11T10:30:00Z",
  "level": "info",
  "event": "metrics_snapshot",
  "queries_executed": 1200,
  "queries_failed": 15,
  "queries_avg_duration_ms": 425
}
```

Future: Prometheus export endpoint at `GET /metrics`.

## Troubleshooting

### Benchmarker Logging

The benchmarker module logs key events during generation and testing:

- `generation.py`: document sampling count, question generation result, tokens used
- `testing.py`: test run start/completion, per-question metric failures
- `runner.py`: RAG call latency per question, metric computation progress
- `metrics/controller.py`: individual metric errors (logged as warnings, metric returns `None`)

Test results (latency, per-question scores, claim scores, context data) are persisted in the `test_results` table as JSON columns, available for post-hoc analysis via the `/api/v1/benchmarker/test-runs/{id}` endpoint.

### Query is slow

1. Check query trace to identify bottleneck step
2. If `dense_search` is slow: Qdrant collection may be too large, consider sharding
3. If `graph_enrichment` is slow: Memgraph query may be inefficient, review Cypher query
4. If `multi_factor_scoring` is slow: Reduce number of signals or simplify scoring logic

### Sync is failing

1. Check sync logs for errors: `GET /api/v1/connections/{id}/sync-logs`
2. Review connector health check: `POST /api/v1/connections/{id}/health`
3. Verify credentials and permissions in connector config
4. Check rate limits: Look for `rate_limit_hit` events in logs

### Service is not ready

1. Check readiness probe: `GET /ready`
2. Identify unhealthy dependency
3. Verify dependency is running: `docker compose ps`
4. Check dependency logs: `docker compose logs [postgres|qdrant|memgraph|ollama]`
