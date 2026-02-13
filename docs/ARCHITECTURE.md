# Metatron Core Architecture

This document describes the high-level architecture, data flows, and design decisions for Metatron Core.

## Layer Dependency Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ L6: API                                                          │
│     REST endpoints, request/response handling                    │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L5: CHANNELS                                                     │
│     Telegram, Discord, Slack bots - message handling             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L4: AGENT                                                        │
│     Router, orchestration, conversation management               │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L3: DOMAIN SERVICES                                              │
│     connectors | skills | llm | auth                             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L2: PROCESSING                                                   │
│     ingestion | retrieval                                        │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L1: STORAGE                                                      │
│     Qdrant, Memgraph, PostgreSQL clients                         │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ L0: CORE                                                         │
│     Config, interfaces, base classes, utilities                  │
└─────────────────────────────────────────────────────────────────┘
```

### Dependency Rules

The architecture follows strict one-directional dependency flow:

- Each layer can only depend on layers below it (lower layer numbers)
- Lower layers never import from upper layers
- Layer 0 (core) has no internal dependencies
- This ensures modularity and prevents circular dependencies

## Data Flow: Query Processing

When a user sends a query, it flows through the system as follows:

```
1. User Message
   "What is our refund policy for enterprise customers?"
        ↓
2. Channel (Telegram/Discord/Slack)
   - Receives message
   - Extracts user context (workspace_id, user_id)
   - Forwards to Agent
        ↓
3. Agent Router
   - Loads available skills from database
   - Constructs LLM prompt with skill definitions
   - Calls LLM-as-Router (OpenClaw pattern)
   - LLM selects: skill="knowledge_search", needs_retrieval=True
        ↓
4. Skill Selection
   - Agent loads skill definition
   - Determines required tools/parameters
   - Initiates skill execution
        ↓
5. LLM Call (if skill requires generation)
   - Formats prompt with context
   - Calls Ollama/OpenAI/Anthropic
   - Handles streaming if enabled
        ↓
6. Tool Execution
   - Skill determines it needs retrieval
   - Calls retrieval pipeline with query
        ↓
7. Retrieval Pipeline
   - Dense retrieval: embed query, search Qdrant
   - Sparse retrieval: BM25 search in PostgreSQL
   - Graph retrieval: find related entities in Memgraph
   - Fusion: RRF combines results
   - Scoring: apply 6 ranking signals
   - Rerank: final ordering
   - Return top-k chunks
        ↓
8. Response Generation
   - LLM generates answer from retrieved context
   - Agent formats response
   - Includes source citations
        ↓
9. Tracing (parallel to all steps)
   - Log each step with timing
   - Record skill usage, LLM calls, retrieval hits
   - Store in PostgreSQL for analytics
        ↓
10. Channel
   - Formats response for platform
   - Sends to user
```

## Data Flow: Document Ingestion

When a connector fetches documents, they are processed as follows:

```
1. Connector Trigger
   - Scheduled job or manual trigger
   - connector.fetch() called for source (e.g., Confluence)
        ↓
2. Document Fetch
   - Connector authenticates to external API
   - Retrieves documents, pages, or files
   - Extracts metadata (title, author, timestamp, URL)
        ↓
3. Ingestion Pipeline
   - Receives raw documents
   - Validates format and required fields
        ↓
4. Parse
   - Converts HTML, Markdown, PDF to plain text
   - Preserves structure (headers, lists, tables)
   - Extracts embedded links and references
        ↓
5. Chunk (Root-Child)
   - Creates root chunk: full document summary
   - Creates child chunks: semantic sections (512-1024 tokens)
   - Maintains parent-child relationships
   - Overlaps chunks by 128 tokens for context continuity
        ↓
6. Deduplication (SimHash)
   - Compute SimHash fingerprint for each chunk
   - Compare with existing fingerprints in PostgreSQL
   - Skip chunks with >95% similarity
        ↓
7. Embed
   - Generate dense embeddings (sentence-transformers or OpenAI)
   - Create sparse embeddings (BM25 term weights)
        ↓
8. Store
   - Qdrant: insert vector embeddings + metadata
   - Memgraph: create nodes (Document, Chunk, Entity)
   - Memgraph: create edges (CONTAINS, REFERENCES, MENTIONS)
   - PostgreSQL: store document metadata, chunk text, SimHash
        ↓
9. Graph Enrichment (async)
   - Extract entities (NER or LLM-based)
   - Link entities across documents
   - Create RELATED_TO edges
        ↓
10. Index Update
   - Update search indexes
   - Trigger reindex if schema changed
```

## Key Design Decisions

### 1. LLM-as-Router (OpenClaw Pattern)

Instead of hardcoded routing logic, we use an LLM to select the appropriate skill:

- **Why**: Flexible, natural language understanding, easy to add new skills
- **How**: Agent constructs prompt with skill definitions (name, description, parameters), LLM returns skill name + arguments
- **Tradeoff**: Adds 100-300ms latency, requires LLM call per query
- **Mitigation**: Cache common routing decisions, use fast LLM (e.g., GPT-3.5-turbo, Ollama with small model)

### 2. Graceful Degradation

All external calls are wrapped in `_safe_call` functions:

- **Why**: Network failures, API rate limits, and database timeouts should not crash the agent
- **How**: Try/except with logging, return partial results or fallback values
- **Example**: If Memgraph is down, retrieval falls back to Qdrant-only search

### 3. Skills in Database, Not Files

Skill definitions are stored as Markdown in PostgreSQL:

- **Why**: Non-engineers (PMs, support) can add/edit skills via UI, no code deployment needed
- **How**: Markdown format with frontmatter (name, description, parameters), body contains prompt template
- **Tradeoff**: Can't use Python imports in skill logic
- **Mitigation**: Skills are prompt templates + tool calls, not executable code

### 4. Hybrid Search with RRF

Combine dense (semantic) and sparse (keyword) search:

- **Why**: Dense embeddings miss exact keyword matches, sparse search misses semantic similarity
- **How**: Retrieve top-100 from each, merge with Reciprocal Rank Fusion (RRF)
- **Formula**: `score(d) = sum(1 / (k + rank_i(d)))` for each retriever i, k=60
- **Benefit**: Robust to query type, works well on both factual and conceptual queries

### 5. Per-Workspace Isolation

All data is scoped to a workspace_id:

- **Why**: Multi-tenant SaaS, enterprise customers need data separation
- **How**: Workspace filter in all database queries (Qdrant, Memgraph, PostgreSQL)
- **Enforcement**: Middleware checks JWT workspace claim, injects into query context
- **Tradeoff**: Can't easily share knowledge across workspaces
- **Future**: Allow opt-in cross-workspace search for parent-child org structures

### 6. Enterprise Extensibility via Interfaces

Core is open-source, enterprise repo extends via interfaces:

- **Why**: Allows proprietary connectors, custom scoring, enterprise-only features
- **How**: Core defines interfaces (e.g., `ConnectorInterface`, `ScorerInterface`), enterprise implements
- **Registry Pattern**: Core registers implementations at runtime via plugin system
- **Example**: Core has `ConfluenceConnector`, enterprise adds `SharePointConnector` by implementing `ConnectorInterface`

## Package Descriptions

### L0: core

Base layer with no dependencies on other packages.

- `config.py`: Environment variables, settings, feature flags
- `interfaces.py`: Abstract base classes for connectors, skills, scorers, etc.
- `exceptions.py`: Custom exception hierarchy
- `logging.py`: Structured logging setup
- `utils.py`: String, date, JSON utilities

### L1: storage

Database clients and low-level data access.

- `qdrant_client.py`: Vector database operations (insert, search, delete)
- `memgraph_client.py`: Graph database operations (Cypher queries)
- `postgres_client.py`: Relational database operations (SQLAlchemy models, queries)
- `redis_client.py`: Cache and task queue

### L2: ingestion

Document processing pipeline.

- `pipeline.py`: Orchestrates parse, chunk, dedup, embed, store
- `parsers/`: HTML, Markdown, PDF, DOCX parsers
- `chunking.py`: Root-child chunking logic (OpenMemory-inspired)
- `deduplication.py`: SimHash computation and comparison
- `embedders.py`: Dense and sparse embedding generation

### L2: retrieval

Search and ranking.

- `pipeline.py`: Orchestrates dense, sparse, graph retrieval and fusion
- `dense_retrieval.py`: Qdrant vector search
- `sparse_retrieval.py`: BM25 PostgreSQL search
- `graph_retrieval.py`: Memgraph entity and relationship search
- `fusion.py`: RRF merging of results
- `scoring.py`: 6-factor relevance scoring (semantic, lexical, recency, authority, graph, user context)
- `reranking.py`: Optional LLM-based reranking

### L3: connectors

External integrations.

- `base.py`: `ConnectorInterface` abstract class
- `confluence.py`: Confluence API client, fetch pages/spaces
- `jira.py`: Jira API client, fetch issues/projects
- `notion.py`: Notion API client, fetch pages/databases
- `github.py`: GitHub API client, fetch repos/issues/PRs
- `google_drive.py`: Google Drive API client, fetch files/folders
- `slack.py`: Slack API client, fetch messages/channels

### L3: skills

Skill definitions and execution.

- `manager.py`: Load skills from DB, execute skill logic
- `executor.py`: Run skill prompts, call tools (retrieval, calculators, etc.)
- `registry.py`: Register custom skill implementations

### L3: llm

LLM providers and prompting.

- `providers/`: Ollama, OpenAI, Anthropic clients
- `prompts.py`: Prompt templates for routing, generation, reranking
- `streaming.py`: SSE streaming for real-time responses

### L3: auth

Authentication and authorization.

- `jwt.py`: Token generation, validation
- `rbac.py`: Role-based access control (admin, user, viewer)
- `middleware.py`: FastAPI middleware for auth checks

### L4: agent

Router and orchestration.

- `router.py`: LLM-as-Router implementation
- `orchestrator.py`: Skill execution flow, tool calls
- `conversation.py`: Conversation state management
- `tracing.py`: 7-step query tracing

### L5: channels

Message platform integrations.

- `telegram.py`: aiogram 3.x handler (long-polling)
- `discord.py`: discord.py 2.x handler (gateway DMs)
- `slack.py`: slack-bolt Socket Mode handler (DMs)
- `base.py`: `ChannelInterface` abstract class

### L6: api

REST API endpoints.

- `main.py`: FastAPI app initialization
- `routes/`: Query, ingestion, admin, auth endpoints
- `schemas.py`: Pydantic request/response models
- `middleware.py`: CORS, logging, error handling

## Extension Points

The enterprise repository extends Metatron Core by:

1. **Implementing Interfaces**: Custom connectors, scorers, skills
2. **Registering Implementations**: Via `registry.register(name, implementation)`
3. **Overriding Config**: Environment variables for enterprise-only settings
4. **Adding Routes**: FastAPI routers for enterprise endpoints
5. **Custom Skills**: Stored in PostgreSQL, loaded at runtime

### Example: Adding a Custom Connector

```python
# enterprise_repo/connectors/sharepoint.py
from metatron.core.interfaces import ConnectorInterface
from metatron.connectors.registry import register_connector

class SharePointConnector(ConnectorInterface):
    def fetch(self, workspace_id: str) -> list[Document]:
        # Fetch documents from SharePoint API
        ...

# Register at startup
register_connector("sharepoint", SharePointConnector)
```

### Example: Adding a Custom Scorer

```python
# enterprise_repo/retrieval/compliance_scorer.py
from metatron.core.interfaces import ScorerInterface
from metatron.retrieval.registry import register_scorer

class ComplianceScorer(ScorerInterface):
    def score(self, chunk: Chunk, query: str, context: dict) -> float:
        # Boost chunks from compliance-approved sources
        if chunk.metadata.get("compliance_approved"):
            return 1.5
        return 1.0

register_scorer("compliance", ComplianceScorer)
```

## Future Improvements

- **Streaming Ingestion**: Real-time document updates via webhooks
- **Multi-modal Retrieval**: Images, videos, audio in knowledge base
- **Agent Memory**: Long-term user preferences and conversation history
- **Federated Search**: Query multiple workspaces with access control
- **Auto-skill Generation**: LLM creates new skills from natural language descriptions
- **Performance Optimizations**: Caching, batch processing, async connectors
