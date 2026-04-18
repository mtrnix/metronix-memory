# Metatron MCP API Reference

Complete reference for all MCP tools exposed by Metatron Core.
For integration patterns and routing guidance see [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md).

## Quick Start

**Endpoint:** `http://<host>:8000/mcp`
**Transport:** Streamable HTTP (MCP protocol)
**Auth:** Bearer token via `METATRON_MCP_API_KEY` env var (optional in dev mode)

### Full HTTP Example

```bash
# Initialize MCP session
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "metatron_search_fast",
      "arguments": {
        "query": "What is MTRNIX-303?",
        "workspace_id": "MTRNIX",
        "top_k": 5
      }
    },
    "id": 1
  }'
```

### Python MCP Client Example

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    headers = {"Authorization": "Bearer <your-api-key>"}
    async with streamablehttp_client("http://localhost:8000/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()

            # Fast search
            result = await session.call_tool("metatron_search_fast", {
                "query": "agent memory architecture",
                "workspace_id": "MTRNIX",
                "top_k": 5,
            })
            print(result.content)
```

---

## Authentication

| Mode | Behavior |
|------|----------|
| `METATRON_MCP_API_KEY` **not set** | All requests allowed (dev mode) |
| `METATRON_MCP_API_KEY` **set** | Requires `Authorization: Bearer <key>` header |

Auth uses timing-safe comparison (`hmac.compare_digest`). Invalid or missing keys
return `PermissionError`.

---

## Workspace Isolation

**Every tool accepts `workspace_id`.** If omitted, defaults to `"default"` — which
typically has no data. Always pass the workspace explicitly.

```json
{
  "query": "search query",
  "workspace_id": "MTRNIX"
}
```

Data (documents, memory records, graph entities) is strictly isolated per workspace.
A search in workspace A never returns results from workspace B.

---

## Tools Reference

### Knowledge Base

#### `metatron_search_fast`

Low-latency vector search. Returns raw document chunks without LLM synthesis.
**Use this as the default search tool** — fast enough for interactive use.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | — | Natural language query or keyword |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `top_k` | integer | no | `10` | Results to return (1–50) |

**Response:**

```json
{
  "results": [
    {
      "doc_label": "jira:MTRNIX-303",
      "title": "[MTRNIX-303] Memory MCP tools",
      "content": "Implement memory_store, memory_search...",
      "source_type": "jira",
      "score": 0.87,
      "url": "https://mtrnix.atlassian.net/browse/MTRNIX-303",
      "date": "2026-04-17"
    }
  ],
  "count": 5,
  "latency_ms": 120
}
```

**Performance:** Target P50 < 800ms. No reranker, HyDE, graph enrichment, or LLM stages.

---

#### `metatron_search`

Full hybrid RAG search with LLM-synthesized answer and source citations.
**Slow (20–60s)** — use only when a complete, cited answer is needed.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | — | Natural language question |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `limit` | integer | no | `10` | Results per page (1–100) |
| `cursor` | string | no | `null` | Pagination cursor (reserved) |
| `include_graph` | boolean | no | `false` | Include graph context (reserved) |

**Response:**

```json
{
  "results": [
    {
      "doc_label": "hybrid_search",
      "title": "RAG Answer",
      "content": "MTRNIX-303 implements memory MCP tools for the Hermes agent runtime. The task covers three tools: memory_store, memory_search, and memory_delete...\n\n📋 [MTRNIX-303] Memory MCP tools — https://mtrnix.atlassian.net/browse/MTRNIX-303",
      "source_type": "hybrid_search",
      "timestamp": null,
      "score": 1.0
    }
  ],
  "has_more": false,
  "next_cursor": null,
  "total": 1
}
```

**Pipeline:** query expansion → classification → dense + sparse + metadata + graph recall →
multi-signal scoring → cross-encoder reranker → token budget → LLM answer generation.

---

#### `metatron_get`

Retrieve a specific document by its unique label.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `doc_label` | string | yes | — | Document label (e.g., `jira:MTRNIX-303`, `confluence:12345`) |
| `workspace_id` | string | no | `"default"` | Workspace containing the document |

**Response:**

```json
{
  "doc_label": "jira:MTRNIX-303",
  "title": "[MTRNIX-303] Memory MCP tools",
  "content": "Full document content...",
  "source_type": "jira",
  "timestamp": "2026-04-17",
  "metadata": {}
}
```

**Errors:**

| Code | When |
|------|------|
| `DOCUMENT_NOT_FOUND` | No document with that label in the workspace |
| `INVALID_PARAMS` | Empty `doc_label` |

**Tip:** Get `doc_label` values from `metatron_search_fast` results.

---

#### `metatron_store`

Index a new document into the knowledge base. Runs the full ingestion pipeline
(chunking, embedding, vector storage).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `content` | string | yes | — | Document content |
| `title` | string | no | `null` | Document title |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `doc_label` | string | no | auto-generated | Unique identifier (`MEM-{hex}` if omitted) |
| `metadata` | object | no | `null` | Additional key-value metadata |

**Response:**

```json
{
  "success": true,
  "doc_label": "MEM-8E6255C7",
  "chunks_stored": 3
}
```

---

### Agent Memory

Agent memory is a separate storage layer from the knowledge base. Memory records are
scoped per agent and support three lifecycle scopes: `global` (shared across agents),
`per_agent` (private to one agent), and `session` (ephemeral, TTL-based).

#### `memory_store`

Persist an agent memory record. Stores across PostgreSQL (source of truth),
Qdrant (vector search), and Neo4j (relationship graph). Deduplicates by content hash.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `content` | string | yes | — | Memory content |
| `agent_id` | string | yes | — | Agent identity |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `scope` | string | no | `"per_agent"` | `global`, `per_agent`, or `session` |
| `tags` | list[string] | no | `[]` | Tag list for filtering |
| `importance_score` | float | no | `0.5` | Importance rating (0.0–1.0) |
| `source_type` | string | no | `""` | Free-form origin label |
| `session_id` | string | no | `null` | **Required** when `scope=session` |

**Response:**

```json
{
  "id": "a441b3ff-1234-5678-9abc-def012345678",
  "content_hash": "e3b0c44298fc1c14...",
  "deduped": false
}
```

`deduped: true` means an existing record with the same content hash was found —
the returned `id` is the existing record's ID.

**Errors:**

| Code | When |
|------|------|
| `INVALID_PARAMS` | Empty content, missing agent_id, invalid scope, missing session_id for session scope |

---

#### `memory_search`

Hybrid search over agent memory. Blends dense vector similarity (Qdrant),
graph relationships (Neo4j), and session recency (Redis).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | — | Natural language query |
| `agent_id` | string | yes | — | Agent identity |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `scope` | string | no | `null` | Filter by scope (`global`, `per_agent`, `session`) |
| `tags` | list[string] | no | `null` | Filter by tags (intersection) |
| `session_id` | string | no | `null` | Session ID for session-boost signal |
| `top_k` | integer | no | `5` | Results to return (1–50) |

**Response:**

```json
{
  "results": [
    {
      "record": {
        "id": "a441b3ff-...",
        "workspace_id": "MTRNIX",
        "agent_id": "hermes",
        "scope": "per_agent",
        "source_type": "conversation",
        "content": "User prefers dark mode",
        "tags": ["preference"],
        "importance_score": 0.8,
        "ttl_expires_at": null,
        "content_hash": "e3b0c44...",
        "created_at": "2026-04-17T10:00:00+00:00",
        "session_id": null,
        "metadata": {}
      },
      "score": 0.75,
      "dense_score": 1.0,
      "graph_score": 0.3,
      "session_boost": 0.0,
      "rank": 1
    }
  ],
  "count": 1
}
```

**Score composition:** `score = 0.6 * dense_score + 0.3 * graph_score + 0.1 * session_boost`
(weights configurable via `METATRON_MEMORY_SEARCH_*` env vars).

---

#### `memory_delete`

Delete a persistent memory record from all stores (PG + Qdrant + Neo4j).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `record_id` | string | yes | — | Record ID to delete |
| `workspace_id` | string | no | `"default"` | Target workspace |

**Response:**

```json
{
  "success": true,
  "found": true
}
```

`found: false` means the record was not in the store (already deleted or never existed).

**Note:** Session-scoped records are managed via the session lifecycle, not this tool.

---

#### `memory_batch_store`

Persist multiple memory records in a single call. Sequential processing for
correct deduplication.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `records` | list[object] | yes | — | Array of `{content, tags?}` objects (max 100) |
| `agent_id` | string | yes | — | Agent identity (same for all records) |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `scope` | string | no | `"per_agent"` | Scope for all records |
| `importance_score` | float | no | `0.5` | Importance for all records (0.0–1.0) |
| `source_type` | string | no | `""` | Origin label for all records |
| `session_id` | string | no | `null` | Required when `scope=session` |

**Response:**

```json
{
  "stored": 2,
  "deduped": 0,
  "results": [
    {"id": "abc...", "content_hash": "e3b...", "deduped": false, "error": null},
    {"id": "def...", "content_hash": "f4c...", "deduped": false, "error": null}
  ]
}
```

Individual record failures do not abort the batch — failed records have `error` set
instead of `id`.

---

#### `memory_list`

Enumerate all memory records for an agent with pagination and optional filters.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `agent_id` | string | yes | — | Agent identity |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `scope` | string | no | `null` | Filter by scope |
| `tags` | list[string] | no | `null` | Filter by tags (intersection) |
| `limit` | integer | no | `20` | Results per page (1–100) |
| `offset` | integer | no | `0` | Pagination offset |

**Response:**

```json
{
  "records": [
    {
      "id": "abc...",
      "content": "user prefers dark mode",
      "agent_id": "hermes",
      "scope": "per_agent",
      "tags": ["preference"],
      "importance_score": 0.8,
      "content_hash": "e3b...",
      "created_at": "2026-04-17T10:00:00+00:00"
    }
  ],
  "count": 1,
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

`total` is the unfiltered count for pagination. `count` is the number of records
in this page (may be less than `total` due to tags post-filter or pagination).

---

#### `memory_update`

Update an existing memory record in place. Preserves Neo4j relationships.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `record_id` | string | yes | — | Record ID to update |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `content` | string | no | `null` | New content (triggers re-embedding) |
| `tags` | list[string] | no | `null` | Replace tags |
| `importance_score` | float | no | `null` | New importance (0.0–1.0) |

All fields except `record_id` and `workspace_id` are optional. Only provided
fields are updated. If `content` changes, Qdrant re-embeds; if only
`tags`/`importance_score` change, only the payload is updated (no re-embedding).

**Response:**

```json
{
  "id": "abc-123-def",
  "content_hash": "new-hash...",
  "updated_fields": ["content", "tags"]
}
```

---

### System

#### `metatron_status`

Workspace health check and document statistics.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `workspace_id` | string | no | `"default"` | Workspace to check |

**Response:**

```json
{
  "status": "healthy",
  "documents": {"total": 622},
  "last_sync": null,
  "embedding_model": "nomic-embed-text"
}
```

`status` is `"healthy"` when documents exist, `"initializing"` when empty.

---

#### `metatron_sync`

Trigger document sync from registered MCP sources (not Jira/Confluence connectors).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | no | `null` | Specific MCP server name (syncs all if omitted) |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `force_full` | boolean | no | `false` | Force full sync, skip change detection |

**Response:**

```json
{
  "success": true,
  "sources_synced": 0,
  "details": []
}
```

**Note:** This tool syncs external **MCP server** sources (registered in
`.metatron/mcp_servers.json`), not database connectors (Jira, Confluence, etc.).
For connector sync, use the REST API: `POST /api/v1/connections/{id}/sync/`.

---

## Error Handling

All tools return errors in a consistent format:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document not found: jira:MTRNIX-999",
    "hint": "Check the document label or use search to find documents",
    "details": {}
  }
}
```

### Error Codes

| Code | Description |
|------|-------------|
| `INVALID_PARAMS` | Missing or invalid parameters |
| `DOCUMENT_NOT_FOUND` | Document or record not found |
| `INGESTION_FAILED` | Document ingestion pipeline error |
| `WORKSPACE_NOT_FOUND` | Workspace does not exist |
| `QDRANT_UNAVAILABLE` | Qdrant vector database unreachable |
| `GRAPH_UNAVAILABLE` | Neo4j graph database unreachable |
| `AUTH_REQUIRED` | API key validation failed |
| `RATE_LIMITED` | Request rate limit exceeded |
| `INTERNAL_ERROR` | Unexpected server error (check logs) |

---

## Usage Patterns

### Default Flow: Fast Search

For interactive agent use, `metatron_search_fast` should be the primary tool.
The agent receives raw passages and synthesizes its own answer:

```
Agent query → metatron_search_fast → raw chunks → Agent LLM → answer
```

Latency: **100–600ms**

### Deep Research Flow

When a thorough, cited answer is needed, use `metatron_search` (full RAG):

```
Agent query → metatron_search → synthesized answer with citations
```

Latency: **20–60s** (depends on LLM provider)

### Memory Lifecycle

```
1. memory_store(content, agent_id, tags)     → persist a fact/preference
2. memory_search(query, agent_id)            → recall relevant memories
3. memory_delete(record_id)                  → remove outdated memory
```

Deduplication is automatic — storing the same content twice returns the existing
record with `deduped: true`.

### Document Retrieval

When `search_fast` returns a relevant `doc_label`, fetch the full document:

```
1. metatron_search_fast(query)               → results with doc_label
2. metatron_get(doc_label)                    → full document content
```
