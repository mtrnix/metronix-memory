<p align="center">
  <img src="docs/metatron-banner.svg" alt="Metronix Memory" width="600">
</p>

<p align="center">
  <strong>Open-source AI memory infrastructure.</strong> Ingest any data source.<br>
  Ask questions via Hermes, Claude, Cursor, Open WebUI, or any MCP client.<br>
  Answers grounded in your organization's real knowledge - self-hosted, always.
</p>

<p align="center">
  <a href="#what-problem-does-this-solve"><strong>Problem</strong></a> |
  <a href="#architecture">Architecture</a> |
  <a href="#install">Install</a> |
  <a href="#connect-an-agent">Connect an Agent</a> |
  <a href="#documentation">Docs</a>
</p>

---

## What Problem Does This Solve?

**RAG alone isn't enough.** Vector databases retrieve chunks. RAG frameworks wire plumbing. But building an AI agent that actually knows your company - Jira tickets, Confluence pages, GitHub repos, Google Drive, Slack history, uploaded files, and MCP-compatible tools - takes months of integration work.

**Agent memory is still unsolved.** Every AI agent framework ships a `memory.add()` function. Fewer systems answer: "Is this fact still true? When did it last change? Who said it?" Facts go stale silently.

**Self-hosting matters.** Your data, credentials, and knowledge graph should run in your own environment when compliance or privacy requires it.

**Metatron Core** is the open-source answer: hybrid RAG + persistent agent memory + freshness pipeline. Self-hosted. MCP-native. Built for AI agents, not just chatbots.

| Your Agents Need | Without Metatron | With Metatron |
|---|---|---|
| Search company knowledge | Build separate integrations and ingestion pipelines | Connect sources and query through one RAG surface |
| Persistent agent memory | Reset every session or store raw notes | `fact`, `preference`, and `pinned` memory records |
| Freshness checks | Stale facts remain forever | Link, reconcile, monitor, curate, and review memory |
| Agent-native access | Custom tools per runtime | Built-in MCP server for Cursor, Claude Desktop, Hermes, and other MCP clients |
| Self-hosted deployment | Cloud-only memory or managed RAG | Docker Compose on your infrastructure |

---

## Architecture

Metatron Core uses a strict one-way dependency architecture - each layer only imports downward.

```text
L6  api/            REST + OpenAI-compatible API + MCP HTTP mount
L5  channels/       Legacy Telegram, Discord, Slack integrations
L4  agent/          Intent router and compatibility shims
L3  services        Connectors, LLM, MCP, memory, auth, workspaces, knowledge
L2  processing      Ingestion, retrieval, freshness pipeline
L1  storage/        PostgreSQL, Qdrant, Neo4j, Redis clients
L0  core/           Config, models, events, plugin interfaces
```

**[Open interactive architecture diagram](docs/architecture-diagram.html)** - works offline in a browser.

### Key Pipelines

| Pipeline | Flow | What it does |
|---|---|---|
| **Ingestion** | Fetch -> Parse -> Chunk -> Embed -> Store | Incremental sync from connectors and files. PDF, HTML, Office, text, and tabular processors. |
| **Retrieval** | Classify -> Expand -> Recall -> Rerank -> Score -> Answer | Dense vectors + SPLADE sparse retrieval + graph context + source citations. |
| **Freshness** | Linker -> Reconciler -> Monitor -> Curator -> DecisionEngine | Detects stale or conflicting memory and knowledge records. |
| **Memory** | Store -> Search -> Review -> Assemble | Persistent agent memory scoped by workspace and agent. |

---

## Install

The primary installation sequence lives in [`manual.md`](manual.md). Use [`install.md`](install.md) if you hit errors or need detailed deployment notes.

### 1. Clone the repository

```bash
git clone -b develop https://github.com/mtrnix/metatroncore.git
cd metatroncore
```

### 2. Verify Docker and Docker Compose

```bash
docker --version
docker compose version 2>/dev/null || docker-compose --version
docker info >/dev/null 2>&1 && echo "daemon OK" || echo "START DOCKER DAEMON"
```

Docker installation links:

- Linux: <https://docs.docker.com/engine/install/>
- macOS: <https://docs.docker.com/desktop/setup/install/mac-install/>
- Windows: <https://docs.docker.com/desktop/setup/install/windows-install/>

On macOS, Docker Desktop can lose ownership of `~/.docker` after an update. If `docker compose build` fails with `permission denied`, run:

```bash
sudo chown -R $(whoami):staff ~/.docker
```

Plan for about 15 GB of free disk space for images, build cache, volumes, and first-run Ollama models.

### 3. Prepare `.env`

```bash
cp .env.example .env
```

Open `.env` and choose one LLM provider.

DeepSeek:

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-deepseek-key
```

OpenRouter:

```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-your-openrouter-key
```

Ollama from the built-in Compose stack:

```ini
LLM_PROVIDER=ollama
```

External Ollama host:

```ini
LLM_PROVIDER=ollama
OLLAMA_HOST=http://your-ollama-host:11434
```

Custom OpenAI-compatible provider:

```ini
LLM_PROVIDER=custom
CUSTOM_LLM_URL=https://your-llm-endpoint/v1
CUSTOM_LLM_API_KEY=your-key
```

Generate an MCP API key for agents:

```bash
openssl rand -hex 32
```

Set it in `.env`:

```ini
METATRON_MCP_API_KEY=<paste-the-generated-token>
```

External agents use this token when connecting to `http://localhost:8001/mcp`.

### 4. Launch

Backend stack only:

```bash
docker compose -f docker-compose.full.yml up -d --build
```

Backend + Open WebUI chat interface:

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

Open WebUI is available at `http://localhost:3080` when the `openwebui` profile is enabled. First run can take 10-15 minutes while images build and models download.

### 5. Verify

```bash
docker compose -f docker-compose.full.yml ps
curl http://localhost:8001/health
```

Ports:

| Service | Port |
|---|---|
| API | `8001` |
| PostgreSQL | `5433` |
| Qdrant | `6335` |
| Neo4j bolt | `7688` |
| Redis | `6380` |
| Ollama | `11435` |
| SPLADE | `8080` |
| Open WebUI | `3080` |

### Troubleshooting

If installation fails, see [`install.md`](install.md) for the full deployment reference.

Common commands:

```bash
# Clean up a previous run
docker compose -f docker-compose.full.yml down

# Rebuild after .env changes
docker compose -f docker-compose.full.yml up -d --build --force-recreate

# Check API logs
docker compose -f docker-compose.full.yml logs metatron-core
```

---

## Demo

Open [`docs/architecture-diagram.html`](docs/architecture-diagram.html) in any browser for an interactive architecture walkthrough.

After the stack is running, connect an MCP client and ask a question against your indexed knowledge base, for example:

```text
What changed in the project plan this week?
```

Metatron searches your knowledge base and returns a grounded answer with citations from your real data.

---

## How Metatron Compares

### vs. Vector Databases

| | Vector DB | Metatron |
|---|---|---|
| Stores vectors | Yes | Yes, using Qdrant internally |
| Sparse retrieval | Usually add-on | Built-in SPLADE sparse retrieval |
| Knowledge graph | No | Neo4j graph context |
| Document ingestion | Bring your own | Connectors and processors included |
| Agent memory | No | Built-in memory records and lifecycle |
| MCP-native | No | Built-in MCP server |

Use a vector DB alone if you are building a custom RAG stack from scratch. Use Metatron if you want ingestion, retrieval, graph context, memory, and agent access in one system.

### vs. RAG Frameworks

| | RAG Framework | Metatron |
|---|---|---|
| RAG pipeline | You build it | Built in and configurable |
| Connectors | Community integrations | Native connector framework |
| Agent memory | Bring another service | Built in |
| API server | You build it | REST, OpenAI-compatible, and MCP surfaces included |
| Time to first answer | Days or weeks | One Docker Compose stack |

RAG frameworks give you building blocks. Metatron gives you an operational backend for agent knowledge and memory.

### vs. Agent Memory Platforms

| | Memory Platform | Metatron |
|---|---|---|
| Persistent memory | Yes | Yes |
| Hybrid RAG | Often limited | Dense + SPLADE + graph |
| Enterprise data connectors | Usually limited | Connector framework included |
| Self-hosted deployment | Varies | Docker Compose first |
| MCP tools | Varies | Built-in MCP server |

---

## Features

### Hybrid RAG

- Dense vectors + SPLADE sparse vectors + Neo4j graph context.
- Query expansion, classification, reranking, and source diversity.
- Source-grounded answers with citations.

### Connectors And Ingestion

- Native connector framework for Confluence, Jira, Notion, GitHub, Google Drive, Slack history, and local files.
- File upload APIs for direct ingestion.
- MCP tools for storing and syncing external sources.

### Agent Memory

- `fact`, `preference`, and `pinned` memory records.
- Workspace and agent scoping.
- Review queue, snapshots, health checks, and freshness lifecycle support.

### Consumer Surfaces

### Hermes Memory: Important Distinction

If you are using **Hermes Agent**, do **not** start with Hermes' "memory providers"
screen and expect Metatron to appear there.

Hermes currently has two different integration concepts:

- **Memory providers** — Hermes-native provider plugins such as `honcho`, `mem0`,
  `hindsight`, and similar providers configured via Hermes' own memory setup flow
- **MCP servers** — external backends Hermes can call as tools

**Metatron today integrates with Hermes as an MCP server, not as a Hermes-native
memory provider plugin.**

That means:

- use Metatron when you want Hermes to search the KB or read/write memory through
  MCP tools like `metatron_search`, `metatron_memory_search`, and
  `metatron_memory_store`
- use Hermes memory providers when you specifically want Hermes' built-in provider
  plugin system
- use both if you want Hermes-native memory plus Metatron as a richer external
  knowledge and memory backend

**Recommended path today:** connect Hermes to Metatron through `/mcp`.

See:
- **[Hermes Integration Guide](docs/HERMES_INTEGRATION.md)** — exact MCP setup for Hermes
- **[Hermes memory provider docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers)** — what Hermes means by "memory providers"

### Deployment
- **Self-hosted:** Docker Compose, your hardware, your keys
- **Full stack:** PostgreSQL + Qdrant + Neo4j + Ollama + API
- **Planned:** Air-gapped BYOC, SOC2 compliance

---

## Connect An Agent

After Metatron is running, connect your agent through MCP.

The easiest path is to give your agent the prompt from [`connecting_to_agent.md`](connecting_to_agent.md). It asks for the Metatron MCP URL, MCP API key, agent id, and workspace id, then configures and verifies the MCP connection.

Runtime-specific guides:

- [`docs/integrations/cursor.md`](docs/integrations/cursor.md)
- [`docs/integrations/claude-desktop.md`](docs/integrations/claude-desktop.md)
- [`docs/integrations/hermes.md`](docs/integrations/hermes.md)
- [`docs/integrations/openwebui.md`](docs/integrations/openwebui.md)
- [`docs/integrations/librechat.md`](docs/integrations/librechat.md)
- [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md)

---

## Quick Reference

### Development Commands

```bash
make dev              # uvicorn --reload
make test             # pytest unit tests
make lint             # ruff check + format check
make typecheck        # mypy src/metatron/
make migrate          # alembic upgrade head
make eval             # search quality eval
```

### Important URLs

| Surface | URL |
|---|---|
| API health | `http://localhost:8001/health` |
| REST API | `http://localhost:8001/api/v1/*` |
| MCP endpoint | `http://localhost:8001/mcp` |
| OpenAI-compatible API | `http://localhost:8001/v1` |
| Open WebUI | `http://localhost:3080` |

---

## Documentation

- [`manual.md`](manual.md) - primary step-by-step install sequence.
- [`install.md`](install.md) - detailed deployment and troubleshooting reference.
- [`connecting_to_agent.md`](connecting_to_agent.md) - MCP agent connection prompt.
- [`docs/README.md`](docs/README.md) - documentation index.
- [`docs/MCP_API.md`](docs/MCP_API.md) - MCP tool reference.
- [`docs/API.md`](docs/API.md) - REST API reference.
- [`docs/reference/api-openai-compat.md`](docs/reference/api-openai-compat.md) - OpenAI-compatible API reference.
- [`docs/product/legacy.md`](docs/product/legacy.md) - legacy and compatibility surfaces.
- [`docs/product/open-core-boundaries.md`](docs/product/open-core-boundaries.md) - open-core boundaries.

---

## Contributing

Metatron Core is open-core. Bug reports, connector additions, documentation improvements, and focused pull requests are welcome.

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE).

Third-party components, connectors, and plugins may carry their own licenses.

---

<p align="center">
  <sub>Built for AI agents that need to know your organization - not just answer questions.</sub>
</p>
