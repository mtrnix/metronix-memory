# Design Decisions

## Overview

This document explains the key architectural and technical decisions made in the Metatron project, including patterns borrowed from OpenClaw and OpenMemory, technology choices, and project structure.

## Patterns Borrowed from OpenClaw

OpenClaw is an open-source LLM-powered automation framework. Metatron adopts 9 core patterns from its architecture:

### 1. LLM-as-Router

**Pattern**: Use the LLM to route user requests to appropriate tools based on intent, not hard-coded rules.

**Why**: More flexible than traditional NLU pipelines. The LLM understands context and can handle ambiguous requests.

**Implementation**: The LLM reads skill documents (see Skills section) and decides which tools to call based on the user's message.

**Example**:
- User: "Find docs about authentication"
- LLM: Calls `knowledge_search` tool with query "authentication"
- User: "Create a Jira ticket for that"
- LLM: Calls `jira_create_issue` tool with summary from previous context

### 2. Skill System

**Pattern**: Store tool knowledge as structured documents (not code) that the LLM reads at runtime.

**Why**: Easier to update tool usage without changing LLM training. Non-technical users can edit skills via API.

**Implementation**: Skills are Markdown files stored in PostgreSQL. Each skill teaches the LLM how to use a specific tool.

**Example**: The `jira_actions` skill contains:
```markdown
# Jira Actions

To create a Jira issue, call:
{
  "tool": "jira_create_issue",
  "parameters": {
    "project_key": "PROJ",
    "summary": "Issue title"
  }
}
```

### 3. Channel Adapter Pattern

**Pattern**: Abstract external integrations behind a common interface.

**Why**: Decouples business logic from connector implementation. Easy to add new connectors without changing the core system.

**Implementation**: `ConnectorInterface` defines `configure()`, `fetch()`, `health_check()`. All connectors implement this interface.

**Example**: Confluence, Jira, GitHub connectors all implement the same interface, so the sync engine doesn't need to know which connector it's using.

### 4. Graceful Degradation (_safe_call)

**Pattern**: Wrap external calls in error handling that returns fallback values on failure.

**Why**: Non-critical failures shouldn't crash the entire pipeline. Systems should degrade gracefully.

**Implementation**: `_safe_call()` utility function:
```python
async def _safe_call(func, default_value, error_message: str):
    try:
        return await func()
    except Exception as e:
        logger.warning("safe_call_failed", error=str(e), message=error_message)
        return default_value
```

**Example**: If graph enrichment fails, return empty list and continue with other results.

### 5. Tool Executor with Allowlists

**Pattern**: Execute tool calls only if the tool is in an explicit allowlist for the workspace.

**Why**: Security and control. Workspaces can disable dangerous tools or limit LLM capabilities.

**Implementation**: `ToolExecutor` checks `workspace.allowed_tools` before executing any tool call.

**Example**:
```python
if tool_name not in workspace.allowed_tools:
    raise PermissionError(f"Tool {tool_name} not allowed in this workspace")
```

### 6. Registry Pattern

**Pattern**: Use a registry to dynamically load and instantiate connectors/tools without hard-coded imports.

**Why**: Makes the system extensible. New connectors/tools can be added without modifying existing code.

**Implementation**: `ConnectorRegistry` maps connector names to classes:
```python
_connectors = {
    "confluence": ConfluenceConnector,
    "jira": JiraConnector,
    "github": GitHubConnector
}

def get_connector(name: str) -> ConnectorInterface:
    return _connectors[name]()
```

### 7. Config-Driven Activation

**Pattern**: Enable/disable features via configuration, not code changes.

**Why**: Deploy once, configure per workspace. A/B testing and gradual rollouts.

**Implementation**: Workspace settings control feature flags:
```python
workspace = {
    "features": {
        "graph_enrichment": True,
        "multi_factor_scoring": True,
        "sparse_search": False
    }
}
```

### 8. Conversation Sessions

**Pattern**: Store conversation history in a session object, not in the LLM prompt.

**Why**: Enables multi-turn conversations. Context persists across requests.

**Implementation**: `ConversationSession` model stores messages and metadata:
```python
class ConversationSession:
    id: str
    workspace_id: str
    user_id: str
    messages: List[Message]
    created_at: datetime
    updated_at: datetime
```

Each message references the session, and the LLM receives recent messages as context.

### 9. Structured Error Hierarchy

**Pattern**: Define a hierarchy of exception types for different error categories.

**Why**: Makes error handling precise. Callers can catch specific errors and handle them differently.

**Implementation**: `src/errors/exceptions.py`:
```python
class MetatronError(Exception):
    """Base exception"""
    pass

class ConnectorError(MetatronError):
    """Connector-related errors"""
    pass

class ValidationError(MetatronError):
    """Configuration/input validation errors"""
    pass

class PermissionError(MetatronError):
    """Authorization errors"""
    pass
```

## Algorithms Borrowed from OpenMemory

OpenMemory is an open-source knowledge graph and RAG system. Metatron adopts 7 algorithms from its retrieval pipeline:

### 1. SimHash Deduplication

**Algorithm**: Use SimHash fingerprints to detect near-duplicate documents before indexing.

**Why**: Reduces index size and prevents duplicate results. Common in knowledge bases with copy-pasted content.

**Implementation**: Compute SimHash for each document during ingestion. If fingerprint matches an existing document, skip indexing.

**Parameters**:
- Hash size: 64 bits
- Similarity threshold: 95% (Hamming distance <= 3)

### 2. Root-Child Chunking

**Algorithm**: Split documents into root chunks (top-level) and child chunks (nested). Link children to their root.

**Why**: Preserves document structure. Allows retrieval of relevant sections while maintaining access to full document.

**Implementation**: During chunking, track hierarchy:
```python
root_chunk = Chunk(id="doc-1-root", content=first_section)
child_chunk = Chunk(id="doc-1-1", content=subsection, parent_id="doc-1-root")
```

Graph stores relationship:
```cypher
CREATE (root:Chunk {id: "doc-1-root"})
CREATE (child:Chunk {id: "doc-1-1"})
CREATE (child)-[:CHILD_OF]->(root)
```

### 3. Multi-Factor Scoring (6 Signals)

**Algorithm**: Score each retrieved chunk using 6 independent signals, then compute weighted average.

**Signals**:
1. **Relevance** (40%): Vector similarity score
2. **Recency** (15%): Document age (exponential decay)
3. **Authority** (15%): Source trust level (official docs > Slack)
4. **Completeness** (15%): Root chunks > child chunks
5. **User Engagement** (10%): Historical views, upvotes, shares
6. **Source Trust** (5%): Workspace-configured trust scores per source

**Why**: Vector similarity alone is insufficient. Recent, authoritative, complete content should rank higher.

**Implementation**:
```python
final_score = (
    0.40 * relevance +
    0.15 * recency +
    0.15 * authority +
    0.15 * completeness +
    0.10 * user_engagement +
    0.05 * source_trust
)
```

### 4. Hybrid Search (Dense + Sparse)

**Algorithm**: Run two searches in parallel (dense vector, sparse BM25), then fuse results.

**Why**: Dense vectors capture semantic meaning. Sparse vectors capture exact keyword matches. Combining both improves recall.

**Implementation**:
- Dense search: Query Qdrant with embedding vector
- Sparse search: Query Qdrant with TF-IDF sparse vector
- Fusion: Merge results using RRF (see next section)

### 5. RRF Fusion (Reciprocal Rank Fusion)

**Algorithm**: Combine ranked lists from multiple sources by summing reciprocal ranks.

**Formula**:
```
RRF_score(doc) = sum over all lists: 1 / (k + rank_in_list)
```

**Parameters**:
- k = 60 (standard value from literature)

**Why**: Simple, effective, no hyperparameters to tune. Favors documents that appear high in multiple lists.

**Implementation**:
```python
scores = defaultdict(float)
for rank, doc in enumerate(dense_results):
    scores[doc.id] += 1 / (60 + rank)
for rank, doc in enumerate(sparse_results):
    scores[doc.id] += 1 / (60 + rank)
return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

### 6. Context Assembly with Root Linking

**Algorithm**: Assemble final context window by:
1. Selecting top-scored chunks
2. For each chunk, include its root chunk (if not already in context)
3. Linking to full document for "show more"

**Why**: LLM gets relevant snippet plus full document for deeper exploration.

**Implementation**:
```python
context_chunks = []
token_count = 0

for chunk in sorted_chunks:
    if token_count + chunk.token_count > max_tokens:
        break

    context_chunks.append(chunk)
    token_count += chunk.token_count

    # Add root if not already in context
    if chunk.parent_id and chunk.parent_id not in context_chunk_ids:
        root = await get_chunk(chunk.parent_id)
        context_chunks.append(root)
        token_count += root.token_count

return context_chunks
```

### 7. Per-Workspace Isolation

**Algorithm**: Use separate Qdrant collections and Neo4j namespaces for each workspace.

**Why**: Data isolation for multi-tenant SaaS. No cross-workspace leakage.

**Implementation**:
- Qdrant collection name: `workspace-{workspace_id}`
- Neo4j namespace: Query filtering with `WHERE chunk.workspace_id = $workspace_id`

## Why Python (Not TypeScript)

**Decision**: Metatron is written in Python, not TypeScript/Node.js.

**Reasons**:

1. **ML/NLP Ecosystem**: Python has mature libraries for embeddings (sentence-transformers), chunking (nltk, spacy), and text processing.

2. **Asyncio Maturity**: Python's asyncio is production-ready. async/await for I/O-bound operations works well.

3. **Team Expertise**: Most engineers working on knowledge graphs and RAG have Python experience.

4. **SDK Quality**: Qdrant, Ollama, Neo4j all have excellent Python clients with async support.

5. **Type Safety**: Python 3.11+ with mypy provides strong static type checking (comparable to TypeScript).

**Trade-offs**:
- Python is slower than TypeScript for CPU-bound tasks (mitigated by async I/O)
- Runtime vs compile-time errors (mitigated by mypy strict mode)

## Why Two Repos (Core + Enterprise)

**Decision**: Metatron is split into two repositories:
- `metatron-core`: Open-source, Apache 2.0 license
- `metatron-enterprise`: Closed-source, commercial license

**Reasons**:

1. **Open-Source First**: Core retrieval, connectors, and skills are open. Community can contribute.

2. **Enterprise Extensions**: Features like SSO, audit logs, multi-region replication, SLA monitoring are enterprise-only.

3. **Clean Interfaces**: Enterprise extends via interfaces. No fork needed.

4. **Community Trust**: Open-source code is auditable. No vendor lock-in for core features.

**Implementation**:
- Core defines interfaces (e.g., `AuthProvider`)
- Enterprise implements concrete classes (e.g., `OktaSSOProvider`)
- Enterprise imports core as a dependency

Example:
```python
# metatron-core/src/auth/base.py
class AuthProvider(ABC):
    @abstractmethod
    async def authenticate(self, credentials: Dict) -> User:
        pass

# metatron-enterprise/src/auth/okta.py
from metatroncore.auth.base import AuthProvider

class OktaSSOProvider(AuthProvider):
    async def authenticate(self, credentials: Dict) -> User:
        # Okta SAML implementation
        pass
```

## Why Skills in DB (Not Files)

**Decision**: Skills are stored in PostgreSQL, not as files in the codebase.

**Reasons**:

1. **CRUD via API**: Users can create, update, delete skills via REST API without deploying code.

2. **Workspace-Specific Customization**: Each workspace can have custom skills (e.g., internal tool integrations).

3. **Runtime Flexibility**: LLM reads skills at runtime. No redeploy needed to teach new tools.

4. **Version Control**: Skills have created_at, updated_at timestamps. Rollback is possible.

**Trade-offs**:
- Skills are not in git (mitigated by exporting skills to YAML for backup)
- Builtin skills are still authored as `.md` files, then seeded to DB on first run

## Why Qdrant

**Decision**: Use Qdrant for vector storage, not Pinecone, Weaviate, or Elasticsearch.

**Reasons**:

1. **Native Sparse + Dense**: Qdrant supports both dense and sparse vectors in the same collection. No need for two systems.

2. **Per-Collection Isolation**: Each workspace gets its own collection. No shared index.

3. **Excellent Python Client**: Async client with type hints. Well-maintained.

4. **Self-Hosted**: Can run in Docker. No API keys or external dependencies.

5. **Performance**: Fast enough for 10M+ vectors. In-memory index with disk persistence.

**Trade-offs**:
- Not as mature as Pinecone (but improving rapidly)
- Smaller community than Elasticsearch

## Why Neo4j Community Edition (migrated from Memgraph)

**Decision**: Use Neo4j CE for knowledge graph. Originally chose Memgraph, migrated to Neo4j.

**Originally chose Memgraph** for in-memory speed and Cypher compatibility.

**Migrated to Neo4j CE** because:

1. **Disk-Based Scaling**: Scales to billions of nodes (Memgraph limited by RAM).

2. **Memory System Prerequisite**: Memory records will be graph nodes — need disk-based storage.

3. **Full Cypher Support**: No parser workarounds needed (Memgraph 2.18.1 had keyword collisions, no named parameters).

4. **Concurrent Read/Write**: Neo4j handles it natively (Memgraph crashed on concurrent operations).

5. **Mature Ecosystem**: Wider community, Neo4j Browser (:7474), better tooling.

**Trade-offs**:
- Slightly slower for small graphs (<1M nodes) due to disk I/O vs RAM. Acceptable given scaling requirements.

## Why Ollama

**Decision**: Use Ollama for LLM inference, not OpenAI API or Anthropic API.

**Reasons**:

1. **Self-Hosted**: No API keys needed. Runs on local GPU or CPU.

2. **Model Variety**: Supports Llama, Mistral, Gemma, Phi, and 50+ other models.

3. **Tool Calling Support**: Recent models (Llama 3.1, Mistral 0.3) support function calling natively.

4. **Development Experience**: Fast iteration without API costs or rate limits.

5. **Privacy**: No data leaves the developer's machine.

**Trade-offs**:
- Performance depends on hardware (GPU recommended)
- Quality is lower than GPT-4 or Claude for complex reasoning

**Production**: Metatron can use OpenAI, Anthropic, or other providers by swapping the `LLMProvider` implementation. Ollama is the default for development.

## Why PostgreSQL (Not MongoDB)

**Decision**: Use PostgreSQL for metadata storage, not MongoDB or other NoSQL databases.

**Reasons**:

1. **ACID Transactions**: Critical for workspace isolation and consistency.

2. **Strong Typing**: Schema enforcement prevents bugs.

3. **JSON Support**: PostgreSQL supports JSONB columns for flexible metadata.

4. **Joins and Relations**: Skills, workspaces, connections have complex relationships. SQL joins are cleaner than document references.

5. **Mature Ecosystem**: asyncpg, SQLAlchemy, Alembic are production-ready.

**Trade-offs**:
- Less flexible than MongoDB (mitigated by JSONB columns)
- Vertical scaling limits (acceptable for < 100K workspaces)

## Why Async Everywhere

**Decision**: All I/O operations use async/await, not synchronous blocking calls.

**Reasons**:

1. **Concurrency**: Handle thousands of concurrent requests with minimal threads.

2. **Non-Blocking I/O**: Database, HTTP, and vector store calls don't block the event loop.

3. **Ecosystem Support**: FastAPI, SQLAlchemy 2.0, asyncpg, httpx all support async.

4. **Efficiency**: Lower memory footprint than threading or multiprocessing.

**Trade-offs**:
- Async code is more complex (mitigated by modern Python syntax)
- Some libraries don't support async (use thread pools as needed)

## Why Ruff (Not Pylint/Black/isort)

**Decision**: Use Ruff for linting and formatting, not Pylint, Black, and isort separately.

**Reasons**:

1. **Speed**: Ruff is 10-100x faster than Pylint (written in Rust).

2. **All-in-One**: Combines linting, formatting, and import sorting.

3. **Compatibility**: Ruff rules are compatible with Flake8, Black, and isort.

4. **Modern**: Actively developed, fast bug fixes.

**Trade-offs**:
- Fewer rules than Pylint (but covers most common issues)
- Less customizable than Black (but defaults are sensible)

## Why No Microservices

**Decision**: Metatron is a monolith, not microservices.

**Reasons**:

1. **Simplicity**: One codebase, one deployment, one database.

2. **Performance**: No inter-service latency. All components in one process.

3. **Development Speed**: No coordination between teams. Fast iteration.

4. **Sufficient Scale**: A well-architected monolith can handle 100K+ workspaces.

**When to Split**:
- If a specific component needs independent scaling (e.g., embedding service)
- If different teams need to deploy independently
- If latency between components is acceptable

**Current Architecture**: Metatron is modular (layered, dependency injection) but deployed as a single service. This allows splitting into microservices later if needed.

## Why Agent Registry Lives in Core (Not CC Plugin)

**Context (2026-04-21, MTRNIX-270):** WS4 delivered the Agent Registry backend —
CRUD, lifecycle, versioned config. The task spec called for a new module
`src/metatron/controlcenter/`, but the root `CLAUDE.md` also says the commercial
Control Center is a "separate repo, planned." Which side of the boundary owns
agent identity?

**Decision:** Agent Registry lives **in Core** as a first-class L3 module
(`src/metatron/agents/`), parallel to `memory/` and `workspaces/`. The
`controlcenter/` name was rejected.

**Rationale:**

1. **Agent identity is a core primitive.** `memory_records.agent_id` (migration
   013) already references agents; Hermes integration presupposes a stable
   identifier. Core needs this regardless of whether a CC plugin exists.
2. **Consistent neighbour pattern.** `memory/`, `workspaces/` are L3 identity
   primitives. `agents/` extends the same pattern — same persistence style,
   same DI shape, same RBAC gates.
3. **Plugin-shaped governance, not plugin-shaped identity.** What CC actually
   owns is *policy* on top of identity: 5-role RBAC, budget enforcement,
   memory-bindings enforcement, company/department/team hierarchy, audit log,
   workflow orchestration. These land in the future CC plugin and will
   import from `metatron.agents` rather than duplicate its storage.
4. **Soft-reference between memory and agents.** `memory_records.agent_id`
   stays a free string (no FK). Hermes can write memory without prior
   registration — Core does not add a validation bottleneck. The registry
   is authoritative for "who exists," but not gatekeeping "who may write."
5. **Opaque JSONB for `memory_bindings` and `budget` in MVP.** Core stores
   the blobs, enforces 32 KiB and JSON-serializable, and does not interpret
   the shape. Enforcement (rate limits, memory scope filtering) is a CC
   concern.

**Consequences:**

- `/api/v1/agents/*` is a public REST surface, open-source, permissive RBAC
  (editor to write).
- CC-plugin extension points: subscribe to future `AGENT_CREATED` /
  `AGENT_UPDATED` events (not wired in MTRNIX-270), register middleware that
  enforces 5-role RBAC, wrap `AgentRegistryService` with budget-aware
  decorators via plugin hook.
- If Core ever moves to a CC-only agent model, migration is mechanical
  (rename module, keep PG schema).

**Tradeoff:** external consumers see an "agent registry" in Core that is
*incomplete* without governance. Documented in `docs/HERMES_INTEGRATION.md`
and `docs/LEGACY.md` so integrators know what is and is not enforced.

## Summary

Metatron's design prioritizes:
- **Simplicity**: Monolith, self-hosted, minimal dependencies
- **Extensibility**: Interfaces, registries, config-driven features
- **Performance**: Async I/O, in-memory graph, hybrid search
- **Developer Experience**: Type safety, fast tests, clear architecture
- **Flexibility**: Skills in DB, swappable LLM providers, workspace isolation

These decisions balance immediate practicality (fast development, easy deployment) with long-term maintainability (clean interfaces, modular design).
