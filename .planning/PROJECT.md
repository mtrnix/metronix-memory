# Metatron OpenClaw Integration

## What This Is

Metatron as OpenClaw's advanced knowledge backend - a seamless integration allowing OpenClaw users to replace SQLite/text memory with Metatron's hybrid RAG system (dense vectors + BM25 + knowledge graph) for long-term memory, large context queries, and structured document storage with temporal updates.

Users can install with `curl http://app.mtrnix.com | bash -s` and add a simple config snippet to OpenClaw to connect their AI assistant to a powerful knowledge management system.

## Core Value

**Replace OpenClaw's amnesia with structured, searchable long-term memory.** OpenClaw users get instant access to hybrid RAG (dense + sparse + graph), document ingestion from Confluence/Jira/Notion, and bi-directional memory sync - all through native MCP integration.

## Requirements

### Validated

(Existing Metatron capabilities to leverage)

- ✓ Hybrid RAG search pipeline (dense vectors + BM25 + graph enrichment)
- ✓ Multi-source document ingestion (Confluence, Jira, Notion)
- ✓ Multi-workspace support with isolation
- ✓ MCP client implementation (connecting TO other MCP servers)
- ✓ Graph database integration (Memgraph for knowledge graph)
- ✓ Vector database (Qdrant with hybrid sparse/dense)
- ✓ Conversation history and session management
- ✓ Multi-channel bots (Telegram, Discord, Slack)

### Active

(New capabilities to build)

- [ ] MCP Server implementation exposing Metatron tools to OpenClaw
- [ ] One-line installer script (`curl ... | bash`)
- [ ] OpenClaw config helper / setup wizard
- [ ] Bi-directional memory sync (read + write from OpenClaw)
- [ ] Temporal document versioning
- [ ] Docker-compose / full stack installer option
- [ ] MCP tools: `metatron_search`, `metatron_get`, `metatron_store`, `metatron_sync`
- [ ] Memory plugin alternative (deeper OpenClaw integration)

### Out of Scope

- OpenClaw core modifications (must work with stock OpenClaw)
- Cloud-hosted Metatron as a service (self-hosted only for v1)
- Mobile apps (OpenClaw handles the messaging layer)

## Context

**OpenClaw Memory Today:**
- Plain Markdown files (`MEMORY.md`, `memory/YYYY-MM-DD.md`)
- Limited semantic search via SQLite + embeddings
- No structured document ingestion
- No knowledge graph
- Context rot and hallucinations from limited memory

**OpenClaw Architecture:**
- Native MCP server support at agent level: `agents.list[].mcp.servers[]`
- Memory plugin slot: `plugins.slots.memory` (can be replaced)
- Config at `~/.openclaw/openclaw.json`

**Integration Path:**
- Primary: MCP Server (Metatron exposes tools, OpenClaw connects)
- Alternative: Memory Plugin (deeper integration, replaces internal memory)

**Dream Setup Flow:**
```bash
# User installs OpenClaw
git clone https://github.com/openclaw/openclaw
cd openclaw && ./install.sh

# User installs Metatron
curl http://app.mtrnix.com | bash -s

# User connects them (auto-config or manual)
# Option A: Full stack (Docker)
# Option B: Existing services (connect to running Qdrant/Memgraph/Postgres)
```

## Constraints

- **Tech Stack:** Python 3.12+, Qdrant, Memgraph, PostgreSQL, FastAPI
- **Compatibility:** Must work with stock OpenClaw (no core modifications)
- **Installation:** One-liner installer must handle dependencies gracefully
- **Performance:** Search latency < 500ms for typical queries

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| MCP Server vs Plugin | MCP is native to OpenClaw, cleaner separation, follows architecture patterns | — Pending |
| Docker-compose for full stack | Easiest for users, but need option for existing infrastructure | — Pending |
| Bi-directional sync | Users expect to store memories, not just search | — Pending |

---
*Last updated: 2026-02-22 after initialization*
