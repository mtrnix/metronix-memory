<p align="center">
  <img src="docs/metatron-banner.svg" alt="Metatron Core" width="600">
</p>

<p align="center">
  <strong>Open-source AI memory infrastructure.</strong> Ingest any data source.<br>
  Ask questions via Hermes, Claude, Cursor, or any MCP client.<br>
  Answers grounded in your organization's real knowledge — self-hosted, always.
</p>

<p align="center">
  <a href="#-5-minute-quickstart"><strong>5-Minute Quickstart</strong></a> ·
  <a href="#-architecture">Architecture</a> ·
  <a href="#-what-problem-does-this-solve">Problem</a> ·
  <a href="#-how-metatron-compares">Comparisons</a> ·
  <a href="#-demo">Demo</a>
</p>

---

## ❓ What Problem Does This Solve?

**RAG alone isn't enough.** Vector databases retrieve chunks. LangChain/LangGraph wire plumbing. But building an AI agent that actually *knows* your company — your Jira tickets, Confluence pages, GitHub repos, Google Drive, Slack history, and every MCP-compatible tool — takes months of integration work.

**Agent memory is still unsolved.** Every AI agent framework ships a `memory.add()` function. None of them answer: *"Is this fact still true? When did it last change? Who said it?"* Facts go stale silently.

**Enterprise means air-gapped.** SOC2, HIPAA, compliance — your data can't leave your VPC. Most memory platforms are cloud-only.

**Metatron Core** is the open-source answer: hybrid RAG + persistent agent memory + 5-stage freshness pipeline. Self-hosted. MCP-native. Built for AI agents, not just chatbots.

| Your Agents Need | Without Metatron | With Metatron |
|---|---|---|
| Search Confluence + Jira + Notion | Write 3 API integrations | `/sync confluence`, `/sync jira`, `/sync notion` |
| Persistent agent memory | Reset every session | fact/preference/pinned memory with auto-invalidation |
| Your own LLM, on-premise | Cloud lock-in | Ollama, DeepSeek, OpenRouter, any provider |
| MCP tools for agents | Build custom MCP servers | Built-in MCP server + MCP client for universal connectors |
| Air-gapped deployment | SOC2 nightmare | Docker Compose, your hardware, your keys |

---

## 🏗 Architecture

Metatron Core is a **6-layer strict one-way dependency architecture** — each layer only imports downward.

```
L6  api/            REST + OAI-compat + MCP HTTP mount (FastAPI routes, middleware)
L5  channels/       Telegram, Discord, Slack bots
L4  agent/          Intent router, commands, executor
L3  services        Connectors, LLM, MCP, Memory, Auth, Workspaces, Knowledge
L2  processing      Ingestion pipeline + Retrieval pipeline + Freshness worker
L1  storage/        PostgreSQL, Qdrant, Neo4j, Redis (no business logic)
L0  core/           Config, Interfaces, Models, Events, Plugin (ZERO upward deps)
```

**[→ Open interactive architecture diagram](docs/architecture-diagram.html)** — dark-themed SVG, works offline.

### Key Pipelines

| Pipeline | Flow | What it does |
|---|---|---|
| **Ingestion** | Fetch → Parse → Chunk → Embed → BM25/SPLADE → Dedup → Store | Incremental sync from any connector. PDF, HTML, Office, text processors. |
| **Retrieval** | Classify → Expand → Recall (hybrid) → Rerank → Score → Graph Enrich | Dense vectors + BM25 + Neo4j graph. Date filtering, person detection, Jira key exact match. |
| **Freshness** | Linker → Reconciler → Monitor → Curator → DecisionEngine | Auto-detects stale facts, prompts for updates, prunes expired session memory. |
| **Memory** | Add → Link → Enrich → Context-Assemble | Persistent agent memory with `kind=fact|preference|pinned`. Assembled into agent context automatically. |

---

## ⚡ 5-Minute Quickstart

### Prerequisites
- Docker and Docker Compose
- Python 3.12+

### 1. Clone and start everything

```bash
git clone https://github.com/mtrnix/metatroncore.git
cd metatroncore
cp .env.example .env
# Edit .env with your API keys (at minimum, an LLM provider)
docker compose up -d
```

This starts PostgreSQL, Qdrant, Neo4j, and the Metatron API on `http://localhost:8000`.

### 2. Verify it's alive

```bash
curl http://localhost:8000/ready
# → {"status": "healthy"}
```

### 3. Ingest your first data source

```bash
# From any MCP client (Hermes, Claude Desktop, Cursor):
/sync confluence   # your Confluence instance
/sync jira         # your Jira projects
/sync notion       # your Notion workspace

# Or add any MCP-compatible source:
/mcp add my-server npx my-mcp-server
/mcp sync my-server
```

### 4. Ask a question

```bash
# Via Hermes Agent (MCP), Claude Desktop, Cursor, or OpenWebUI:
"What's the status of the Q2 migration project?"

# Metatron searches your knowledge base and returns
# a grounded answer with citations from your real data.
```

**Done in 5 minutes.** Your agents now have memory.

### Full Stack (with Ollama)

For fully offline deployment with local LLM:

```bash
docker compose -f docker-compose.full.yml up --build
# Auto-pulls nomic-embed-text + llama3.1:8b (~5 GB first run)
# API at http://localhost:8001
```

---

## 🎬 Demo

### Architecture Walkthrough

Open [`docs/architecture-diagram.html`](docs/architecture-diagram.html) in any browser for an interactive, dark-themed architecture diagram.

### Record Your Own Demo

```bash
# Install asciinema
pip install asciinema

# Record a demo session
asciinema rec docs/demo.cast
# ... run through the 5-minute quickstart above ...
# Press Ctrl+D to stop

# Convert to GIF (optional)
asciinema-agg docs/demo.cast docs/demo.gif
```

*Coming soon: hosted demo video. PRs welcome!*

---

## 🔬 How Metatron Compares

### vs. Vector Databases (Pinecone, Weaviate, Qdrant)

| | Vector DB | Metatron |
|---|---|---|
| Stores vectors | ✅ | ✅ (uses Qdrant internally) |
| Full-text search (BM25) | ❌ or add-on | ✅ Built-in hybrid |
| Knowledge graph | ❌ | ✅ Neo4j graph enrichment |
| Document ingestion pipeline | ❌ | ✅ Connectors + processors |
| Agent memory with freshness | ❌ | ✅ fact, preference, pinned + auto-invalidation |
| MCP-native for agents | ❌ | ✅ Built-in MCP server + client |
| Chat surfaces (Telegram, Discord) | ❌ | ✅ Built-in |

**Use a vector DB alone if** you're building a custom RAG pipeline from scratch. **Use Metatron if** you want memory + RAG + ingestion + agents in one box.

### vs. RAG Frameworks (LangChain, LlamaIndex)

| | RAG Framework | Metatron |
|---|---|---|
| RAG pipeline | ✅ You build it | ✅ Built-in, configurable |
| Ingestion connectors | ⚠️ Community integrations | ✅ Native Confluence, Jira, Notion, GitHub, GDrive |
| Agent memory | ❌ Add via Mem0/Letta | ✅ Built-in, freshness-managed |
| MCP server | ❌ | ✅ |
| Self-hosted API | ❌ Add FastAPI yourself | ✅ Built-in |
| Time to first answer | Days/weeks of coding | 5 minutes |

**RAG frameworks give you Legos.** Metatron gives you a finished house. Use a framework if your data sources and agent setup are completely custom. Use Metatron if you want working memory + RAG today.

### vs. Agent Memory Platforms (Mem0, Letta, Zep, Honcho, gbrain)

| | Mem0 | Letta | Zep | Honcho | gbrain | **Metatron** |
|---|---|---|---|---|---|---|
| **Category** | Memory API | Agent platform | Context engineering | Reasoning memory | Brain layer | **Memory + RAG + Agents** |
| **Self-hosted** | ✅ | ✅ | ✅ BYOC/VPC | ❌ Cloud-only | ✅ PGLite | **✅ Air-gapped** |
| **Hybrid RAG** | ⚠️ | ❌ | ❌ | ❌ | ✅ | **✅ Dense + BM25 + Graph** |
| **Agent memory freshness** | ❌ | ❌ | ✅ Temporal auto-invalidation | ⚠️ | ⚠️ | **✅ 5-stage pipeline** |
| **Jira/Confluence native** | ❌ | ❌ | ❌ | ❌ | ❌ | **✅ Built-in** |
| **MCP-native** | ⚠️ | ❌ | ❌ | ⚠️ Plugin | ❌ | **✅ Server + Client** |
| **Multi-source ingestion** | ❌ | ❌ | ✅ | ❌ | ⚠️ Documents | **✅ Any DB/API** |
| **Benchmarks** | ❌ | ❌ | ✅ LoCoMo 94.7% | ✅ SOTA on 4 | ✅ BrainBench | **[Planned — MTRNIX-401](https://mtrnix.atlassian.net/browse/MTRNIX-401)** |
| **Enterprise compliance** | ❌ | ❌ | ✅ SOC2, HIPAA | ❌ | ❌ | **⚠️ Planned** |
| **Open source** | ✅ | ✅ | ✅ Apache 2.0 | Core only | ✅ MIT | **Open-core** |

**Full competitive analysis:** [Confluence — Competitive Analysis: AI Memory & Agent Platforms](https://mtrnix.atlassian.net/wiki/spaces/MTRNIX/pages/64454707)

### vs. LangGraph Memory

LangGraph provides **conversation state management** — checkpointing, persistence, replay. It's a workflow engine with short-term memory.

| | LangGraph Memory | Metatron |
|---|---|---|
| **Memory scope** | Per-conversation / per-thread | **Cross-session, persistent** |
| **Fact lifecycle** | Manual checkpoint save/load | **Auto-invalidation via freshness pipeline** |
| **Knowledge retrieval** | ❌ (bring your own RAG) | **✅ Built-in hybrid RAG** |
| **Document ingestion** | ❌ | **✅ Connectors for Jira, Confluence, etc.** |
| **Memory kinds** | State dict | **fact, preference, pinned** |
| **Best for** | Multi-step agent workflows | **Company brain + agent memory** |

LangGraph and Metatron are complementary — LangGraph orchestrates workflows, Metatron provides the knowledge and persistent memory those workflows draw from.

---

## ✨ Features

### Hybrid RAG
- Dense vectors + BM25/SPLADE sparse vectors + Neo4j knowledge graph enrichment
- Query expansion, date filtering, source diversity, person detection
- Jira key exact match, multi-stage reranking
- Customizable scoring weights

### Connectors
- **Native:** Confluence, Jira, Notion, GitHub, Google Drive, Slack history, local files
- **Universal:** Any MCP-compatible server via `/mcp add`
- Incremental sync — never re-ingest the same document twice

### Agent Memory
- **Three kinds:** `fact` (durable knowledge), `preference` (user settings), `pinned` (must-not-vanish)
- **Freshness pipeline:** Linker → Reconciler → Monitor → Curator → DecisionEngine
- **Workspace-scoped:** Per-team, per-project isolation
- **Auto-assembled** into agent context via Memory Context Assembler

### Consumer Surfaces
- **MCP server** — for Hermes Agent, Claude Desktop, Cursor, and any MCP runtime
- **OpenAI-compatible API** (`/v1/chat/completions`) — OpenWebUI, LibreChat
- **REST API** (`/api/v1/*`) — documents, memory, workspaces, connectors, graph
- **Chat bots** — Telegram, Discord, Slack (legacy, migrating to external bot pattern)

### Deployment
- **Self-hosted:** Docker Compose, your hardware, your keys
- **Full stack:** PostgreSQL + Qdrant + Neo4j + Ollama + API
- **Planned:** Air-gapped BYOC, SOC2 compliance

---

## 💻 Quick Reference

### Bot Commands (Telegram, Discord, Slack)

| Command | What it does |
|---|---|
| `/search <query>` | Search your knowledge base |
| `/sync confluence\|jira\|notion` | Incremental sync |
| `/sync confluence\|jira\|notion full` | Full re-sync |
| `/mcp list\|add\|remove\|sync\|tools` | Manage MCP servers |
| `/rebuild-aliases` | Rebuild person name registry |
| `/status` | Workspace stats |
| `/clear` | Clear conversation history |
| `/help` | List all commands |

### Development Commands

```bash
make dev              # uvicorn --reload on :8000
make test             # pytest (unit, no live services)
make lint             # ruff check + format
make typecheck        # mypy src/metatron/
make migrate          # alembic upgrade head
make eval             # search quality eval
make grid-search      # optimal scoring weights
```

### Port Map

| Service | Dev | Full Stack |
|---|---|---|
| PostgreSQL | 5432 | 5433 |
| Qdrant | 6333 | 6335 |
| Neo4j | 7687 | 7688 |
| Ollama | 11434 | 11435 |
| API | 8000 | 8001 |

---

## 📖 Documentation

- **[Architecture Diagram](docs/architecture-diagram.html)** — Interactive, dark-themed SVG
- **[Hermes Integration Guide](docs/HERMES_INTEGRATION.md)** — Connect Metatron to Hermes Agent
- **[Installation Guide](docs/INSTALL.md)** — Detailed setup + troubleshooting
- **[Competitive Analysis](https://mtrnix.atlassian.net/wiki/spaces/MTRNIX/pages/64454707)** — Full landscape (Confluence)
- **[Strategy ADR](docs/adr/2026-04-25-metatron-strategy.md)** — Architectural decisions + pilot plan

---

## 🤝 Contributing

Metatron Core is open-core. We welcome contributions:

1. **Issues:** Bug reports, feature requests
2. **PRs:** Bug fixes, connector additions, documentation improvements
3. **Discussions:** Architecture feedback, memory design, benchmark contributions

See [`CLAUDE.md`](CLAUDE.md) for detailed architecture and development conventions.

---

## 📄 License

Metatron Core source code is available under a source-available license. See [LICENSE](LICENSE) for details.

Third-party components (connectors, plugins) may carry their own licenses.

---

<p align="center">
  <sub>Built for AI agents that need to know your enterprise — not just answer questions.</sub>
</p>
