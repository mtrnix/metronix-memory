# Feature Research

**Domain:** MCP-based Knowledge Backend Integration
**Researched:** 2026-02-22
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Semantic search** | Core RAG capability; users want to find relevant documents by meaning, not keywords | LOW | Vector similarity search is baseline; ChromaDB, Qdrant, pgvector all provide this |
| **Document ingestion** | Users need to add content to the knowledge base | MEDIUM | Support for common formats (PDF, DOCX, TXT, MD); chunking strategy matters |
| **Retrieve by ID/label** | Direct lookup for known items (e.g., Jira keys like PROJ-123) | LOW | Simple key-value lookup; essential for exact matches |
| **Store/write memories** | Bi-directional: users expect to save learnings, not just read | MEDIUM | Create entities, add observations, store relations |
| **Tool discovery** | MCP clients need to understand what tools exist and how to use them | LOW | Proper tool names, descriptions, typed schemas |
| **Pagination** | Large result sets must not overwhelm context window | LOW | Return metadata: `has_more`, `next_offset`, `total_count` |
| **Error guidance** | Agents self-correct based on error messages | LOW | Helpful strings, not exceptions: "User not found. Try searching by email." |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Hybrid search (dense + BM25)** | Combines semantic understanding with exact keyword matching; handles technical terms, proper nouns better | MEDIUM | Qdrant supports sparse vectors; significantly improves recall |
| **Knowledge graph enrichment** | Entity relationships provide context beyond text; "Who works with whom on what project" | HIGH | Requires Memgraph/Neo4j; graph traversal adds latency but improves answer quality |
| **Query expansion** | LLM adds synonyms, related terms before search; improves recall for ambiguous queries | MEDIUM | Needs LLM call; ~100-200ms overhead |
| **Multi-source ingestion** | Native connectors for Confluence, Jira, Notion; enterprise users have data scattered across tools | HIGH | Each connector needs auth, pagination, incremental sync |
| **Workspace isolation** | Multi-tenant support; different teams/projects have separate knowledge bases | MEDIUM | Critical for enterprise; adds complexity to all operations |
| **Temporal filtering** | Date-aware queries: "What did we decide last week?" | MEDIUM | Requires date extraction + indexing; ±7 day widening pattern |
| **Person/activity queries** | "What is Jane working on?" resolves names, filters by assignee/status | MEDIUM | Alias registry + status filtering; language-aware (Russian case endings) |
| **Language detection** | Respond in user's language; detect Cyrillic vs Latin automatically | LOW | 30% threshold for Russian; improves UX for multilingual teams |
| **Streaming responses** | SSE for long-running searches; users see progress, not just spinner | MEDIUM | FastAPI + SSE; essential for >500ms queries |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Thin REST API wrapper** | "Just expose our existing endpoints" | Forces agents to orchestrate multiple calls; bloats context; slow iteration | Design outcome-oriented tools: `track_order(email)` not `get_user()` + `get_orders()` |
| **Complex nested arguments** | "We need flexible filters" | Agents hallucinate keys; miss required fields; `dict[str, Any]` is opaque | Flatten to primitives with `Literal` types: `status: Literal["pending", "shipped"]` |
| **Unbounded result sets** | "Return everything, agent will filter" | Context window overflow; hundreds of results = broken conversation | Paginate with `limit` (default 20-50); return `has_more`, `next_offset` |
| **Raw API responses** | "Just pass through what the API returns" | Bloats context with irrelevant fields; agents extract from nested structures | Curate responses: return `{"subject": str, "body": str}` not full MIME payload |
| **Too many tools** | "Expose all capabilities" | Discovery cost; agent struggles to find right tool; 50+ tools = unusable | 5-15 tools per server; split by persona (admin/user) or domain |
| **Real-time sync** | "Keep everything up to date instantly" | Complexity spike; webhook infrastructure; rate limiting; partial failures | Incremental sync on demand; `/sync` command for user-triggered updates |
| **Full-text search only** | "Elasticsearch is fast" | Misses semantic matches; "authentication bug" won't find "login issue" | Hybrid: combine BM25 for keywords + vectors for semantics |

## Feature Dependencies

```
Semantic Search (baseline)
    └──requires──> Document Ingestion + Chunking
                        └──requires──> Embedding Model

Knowledge Graph Enrichment
    └──requires──> Entity Extraction
    └──requires──> Graph Database (Memgraph/Neo4j)
    └──enhances──> Hybrid Search

Multi-source Ingestion
    └──requires──> Workspace Isolation (for multi-tenant)
    └──requires──> Incremental Sync (for efficiency)

Person/Activity Queries
    └──requires──> Alias Registry (name resolution)
    └──requires──> Status/Assignee Indexing

Temporal Filtering
    └──requires──> Date Extraction from Text
    └──requires──> Date Indexing in Vector Store

Streaming Responses ──conflicts──> Simple JSON Responses (choose one per endpoint)
```

### Dependency Notes

- **Knowledge Graph requires Entity Extraction:** Must identify entities before relating them. Can use LLM-based extraction or NER models.
- **Multi-source Ingestion requires Workspace Isolation:** Without isolation, syncing multiple orgs' Confluence instances would merge unrelated data.
- **Streaming conflicts with Simple JSON:** SSE is more complex to implement and test; start with JSON, add streaming for slow operations.

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] **`metatron_search(query, limit=10)`** — Hybrid search (dense + BM25) over ingested documents. Returns curated results with source labels.
- [ ] **`metatron_get(doc_label)`** — Direct lookup by document label (Jira key, Confluence page ID).
- [ ] **`metatron_store(content, metadata)`** — Store a memory/document with optional metadata.
- [ ] **`metatron_status()`** — System health: doc count, last sync, embedding model status.
- [ ] **Basic document ingestion** — Support TXT, MD, PDF upload via API (not MCP tool, but prerequisite).

**Rationale:** These 4 tools cover the core read/write loop. Search and get for retrieval, store for persistence, status for debugging. No graph enrichment in MVP — that's a differentiator.

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] **`metatron_sync(source)`** — Trigger incremental sync for Confluence/Jira/Notion. Validates multi-source value.
- [ ] **`metatron_list_sources()`** — Show configured connectors and their sync status.
- [ ] **Temporal filtering** — Add `date_range` parameter to `metatron_search`.
- [ ] **Graph entities as resources** — Expose knowledge graph via MCP resources (not tools).

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] **Streaming responses** — SSE for long searches; requires more infrastructure.
- [ ] **Person/activity query handling** — Alias registry + status filtering; language-specific patterns.
- [ ] **Query expansion** — LLM-based synonym injection; latency tradeoff.
- [ ] **Memory plugin integration** — Deeper OpenClaw integration via plugin slot vs MCP server.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Semantic search | HIGH | LOW | P1 |
| Document ingestion | HIGH | MEDIUM | P1 |
| Retrieve by ID | HIGH | LOW | P1 |
| Store/write | HIGH | MEDIUM | P1 |
| Tool discovery | HIGH | LOW | P1 |
| Pagination | MEDIUM | LOW | P1 |
| Hybrid search (BM25) | HIGH | MEDIUM | P1 |
| Knowledge graph | HIGH | HIGH | P2 |
| Multi-source ingestion | HIGH | HIGH | P2 |
| Workspace isolation | MEDIUM | MEDIUM | P2 |
| Temporal filtering | MEDIUM | MEDIUM | P2 |
| Person/activity queries | MEDIUM | MEDIUM | P3 |
| Language detection | LOW | LOW | P3 |
| Streaming responses | MEDIUM | MEDIUM | P3 |
| Query expansion | MEDIUM | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Official MCP Memory | RAG-MCP | Neo4j MCP | Our Approach |
|---------|---------------------|---------|-----------|--------------|
| **Search** | `search_nodes` (graph-based) | `query_documents` (vector) | `run_query` (Cypher) | Hybrid: vector + BM25 + graph |
| **Store** | `create_entities`, `create_relations` | Ingestion only | Write queries | `metatron_store` + graph auto-extraction |
| **Direct lookup** | `open_nodes` | None | Query by ID | `metatron_get` by doc_label |
| **Schema** | `read_graph` | `get_rag_status` | `get_schema` | `metatron_status` + resources |
| **Delete** | Full CRUD | None | Cypher delete | Defer to v2 (soft delete) |
| **Graph** | Knowledge graph (local JSON) | None | Full Cypher access | Memgraph with auto-enrichment |
| **Multi-source** | None | File-based | External DB | Confluence, Jira, Notion connectors |

### Key Differentiation

1. **Hybrid search** — Most competitors are vector-only or graph-only. We combine both.
2. **Enterprise connectors** — Official memory server is local-only; we sync from Confluence/Jira/Notion.
3. **Outcome-oriented tools** — Following Phil Schmid's best practices: `metatron_search` returns ready-to-use results, not raw chunks.
4. **Bi-directional** — Both read (search) and write (store), unlike RAG-MCP which is read-only.

## MCP Tool Design Best Practices

Based on research from [Phil Schmid](https://www.philschmid.de/mcp-best-practices) and [OWASP MCP Security Guide](https://genai.owasp.org/resource/a-practical-guide-for-secure-mcp-server-development/):

### Tool Naming Convention

```
{service}_{action}_{resource}

Examples:
- metatron_search_documents
- metatron_get_document  
- metatron_store_memory
- metatron_sync_source
```

### Argument Design

```python
# BAD: Complex nested dict
def search(filters: dict) -> list: ...

# GOOD: Flattened primitives with constraints
def search(
    query: str,
    source: Literal["confluence", "jira", "notion", "all"] = "all",
    date_from: str | None = None,  # ISO format: "2024-01-01"
    date_to: str | None = None,
    limit: int = 10,
) -> list: ...
```

### Response Curation

```python
# BAD: Raw API response
return api_response  # {"data": {"attributes": {"body": {"value": "..."}}}}

# GOOD: Curated for agent consumption
return {
    "results": [
        {
            "id": doc["id"],
            "title": doc["title"],
            "snippet": doc["content"][:500],
            "source": doc["type"],
            "url": doc["url"],
        }
        for doc in documents[:limit]
    ],
    "has_more": len(documents) > limit,
    "total": len(documents),
}
```

### Tool Count Guideline

- **5-15 tools per server** — Beyond this, discovery becomes slow and error-prone
- **One server, one job** — Don't combine unrelated capabilities
- **Split by persona** — Admin tools vs user tools can be separate servers

## Sources

- [Official MCP Memory Server](https://mcprepository.com/modelcontextprotocol/memory) — 9 tools for knowledge graph memory (HIGH confidence, official)
- [RAG-MCP Server](https://github.com/alejandro-ao/RAG-MCP) — FastMCP + ChromaDB implementation (HIGH confidence, source code)
- [MCP Best Practices — Phil Schmid](https://www.philschmid.de/mcp-best-practices) — Tool design guidelines (HIGH confidence, industry expert)
- [Neo4j MCP Server](https://github.com/neo4j/mcp) — Graph database MCP tools (HIGH confidence, official)
- [Memgraph MCP Server](https://memgraph.com/blog/introducing-memgraph-mcp-server) — GraphRAG patterns (MEDIUM confidence, vendor docs)
- [OWASP MCP Security Guide](https://genai.owasp.org/resource/a-practical-guide-for-secure-mcp-server-development/) — Security considerations (HIGH confidence, OWASP)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — Protocol implementation patterns (HIGH confidence, official)
- [Context7 MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) — Tool definitions (HIGH confidence, official spec)

---
*Feature research for: MCP-based Knowledge Backend Integration*
*Researched: 2026-02-22*
