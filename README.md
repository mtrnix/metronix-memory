<p align="center">
  <img src="docs/metronix-banner.svg" alt="Metronix Memory" width="600">
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

**Metronix Core** is the open-source answer: hybrid RAG + persistent agent memory + freshness pipeline. Self-hosted. MCP-native. Built for AI agents, not just chatbots.

| Your Agents Need | Without Metronix | With Metronix |
|---|---|---|
| Search company knowledge | Build separate integrations and ingestion pipelines | Connect sources and query through one RAG surface |
| Persistent agent memory | Reset every session or store raw notes | `fact`, `preference`, and `pinned` memory records |
| Freshness checks | Stale facts remain forever | Link, reconcile, monitor, curate, and review memory |
| Agent-native access | Custom tools per runtime | Built-in MCP server for Cursor, Claude Desktop, Hermes, and other MCP clients |
| Self-hosted deployment | Cloud-only memory or managed RAG | Docker Compose on your infrastructure |

---

## Architecture

Metronix Core uses a strict one-way dependency architecture - each layer only imports downward.

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

Get a backend running in four steps. This is the shortest path; for the full guide
(prerequisites, Open WebUI, ports, troubleshooting) see [`install.md`](install.md).


### 1. Clone
```bash
git clone -b develop https://github.com/mtrnix/metronix-memory.git
cd metronix-memory
```

**Quick install** — one script replaces steps 2–4: checks Docker, writes `.env`, builds and starts the stack, and health-checks it.
Flags: `--provider`, `--api-key`, `--openwebui`, `--reconfigure`, `--yes` (`./install.sh --help`).

```bash
./install.sh
```

*Prefer manual setup? Continue with step 2 below.*

### 2. Configure: pick one LLM provider + set an MCP key in .env
```bash
cp .env.example .env
```
In .env, set the MCP auth key. The default LLM is the bundled Ollama (works out of
the box). To use an external OpenAI-compatible endpoint (DeepSeek, OpenRouter, vLLM, …)
instead, set the provider block too:
```bash
METRONIX_MCP_API_KEY=...                        # generate one using: openssl rand -hex 32

# Optional — external LLM instead of bundled Ollama:
LLM_PROVIDER=custom
LLM_PROVIDER_URL=https://your-llm-endpoint/v1   # e.g. https://api.deepseek.com/v1
LLM_PROVIDER_API_KEY=your-key
LLM_PROVIDER_MODEL=deepseek-chat                # model the endpoint serves
```
### 3. Launch (first run builds images + pulls models, ~10-15 min)
```bash
docker compose -f docker-compose.full.yml up -d --build
```
### 4. Verify
```bash
curl http://localhost:8000/health
```

A healthy backend exposes the REST API, the OpenAI-compatible API at `:8000/v1`, and the
MCP endpoint at `:8000/mcp` (default on the host: `http://localhost:8000/mcp` — the
**`metronix-full-api`** container, path `/mcp`; from Docker network: `http://metronix-core:8000/mcp`).

**Next steps:**

- [`install.md`](install.md) — full installation info: prerequisites, Open
  WebUI, ports, and troubleshooting.
- [`connecting_to_agent.md`](connecting_to_agent.md) — connect an agent over MCP and give it
  durable memory.
- [`prompts.md`](prompts.md) — the agent setup prompts, ready to paste.

---


## Connect An Agent

After Metronix is running, connect your agent through MCP. See
[`connecting_to_agent.md`](connecting_to_agent.md) for the full walkthrough, which offers two
paths:

- **Prompt-based** — paste the prompts from [`prompts.md`](prompts.md) into your agent and it
  configures itself. The fastest path.
- **Manual** — register the MCP connection by hand, no LLM involved (memory policy and
  migration are done via the prompts).

Either way you give the agent four values: the Metronix MCP URL, the MCP API key, an agent
id, and a workspace id.

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
make typecheck        # mypy src/metronix/
make migrate          # alembic upgrade head
make eval             # search quality eval
```

### Important URLs

| Surface | URL |
|---|---|
| API health | `http://localhost:8000/health` |
| REST API | `http://localhost:8000/api/v1/*` |
| MCP endpoint | `http://localhost:8000/mcp` (`metronix-full-api` / `metronix-core:8000` + `/mcp`) |
| OpenAI-compatible API | `http://localhost:8000/v1` |
| Open WebUI | `http://localhost:3080` |

---

## Documentation

- [`install.md`](install.md) - full installation: prerequisites, providers, ports, troubleshooting.
- [`connecting_to_agent.md`](connecting_to_agent.md) - connect an agent over MCP (prompt-based or manual).
- [`prompts.md`](prompts.md) - the agent setup prompts, ready to paste.
- [`docs/README.md`](docs/README.md) - documentation index.
- [`docs/MCP_API.md`](docs/MCP_API.md) - MCP tool reference.
- [`docs/API.md`](docs/API.md) - REST API reference.
- [`docs/reference/api-openai-compat.md`](docs/reference/api-openai-compat.md) - OpenAI-compatible API reference.
- [`docs/product/legacy.md`](docs/product/legacy.md) - legacy and compatibility surfaces.
- [`docs/product/open-core-boundaries.md`](docs/product/open-core-boundaries.md) - open-core boundaries.
- [`docs/benchmarks/longmemeval.md`](docs/benchmarks/longmemeval.md) - LongMemEval-S agent-memory benchmark.

---


## How Metronix Compares

### vs. Vector Databases

| | Vector DB | Metronix |
|---|---|---|
| Stores vectors | Yes | Yes, using Qdrant internally |
| Sparse retrieval | Usually add-on | Built-in SPLADE sparse retrieval |
| Knowledge graph | No | Neo4j graph context |
| Document ingestion | Bring your own | Connectors and processors included |
| Agent memory | No | Built-in memory records and lifecycle |
| MCP-native | No | Built-in MCP server |

Use a vector DB alone if you are building a custom RAG stack from scratch. Use Metronix if you want ingestion, retrieval, graph context, memory, and agent access in one system.

### vs. RAG Frameworks

| | RAG Framework | Metronix |
|---|---|---|
| RAG pipeline | You build it | Built in and configurable |
| Connectors | Community integrations | Native connector framework |
| Agent memory | Bring another service | Built in |
| API server | You build it | REST, OpenAI-compatible, and MCP surfaces included |
| Time to first answer | Days or weeks | One Docker Compose stack |

RAG frameworks give you building blocks. Metronix gives you an operational backend for agent knowledge and memory.

### vs. Agent Memory Platforms

| | Memory Platform | Metronix |
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
screen and expect Metronix to appear there.

Hermes currently has two different integration concepts:

- **Memory providers** — Hermes-native provider plugins such as `honcho`, `mem0`,
  `hindsight`, and similar providers configured via Hermes' own memory setup flow
- **MCP servers** — external backends Hermes can call as tools

**Metronix today integrates with Hermes as an MCP server, not as a Hermes-native
memory provider plugin.**

That means:

- use Metronix when you want Hermes to search the KB or read/write memory through
  MCP tools like `metronix_search`, `metronix_memory_search`, and
  `metronix_memory_store`
- use Hermes memory providers when you specifically want Hermes' built-in provider
  plugin system
- use both if you want Hermes-native memory plus Metronix as a richer external
  knowledge and memory backend

**Recommended path today:** connect Hermes to Metronix through `/mcp`.

See:
- **[Hermes Integration Guide](docs/integrations/hermes.md)** — exact MCP setup for Hermes
  (includes required tool permissions for prompt-based setup)
- **[Hermes memory provider docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers)** — what Hermes means by "memory providers"
- **[Hermes Tools](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools)** — enable `file`, `terminal`, and `code_execution` if missing



## Contributing

Metronix Core is open-core. Bug reports, connector additions, documentation improvements, and focused pull requests are welcome.

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

Apache License 2.0. See [`LICENSE`](LICENSE).

Third-party components, connectors, and plugins may carry their own licenses.

---

<p align="center">
  <sub>Built for AI agents that need to know your organization - not just answer questions.</sub>
</p>